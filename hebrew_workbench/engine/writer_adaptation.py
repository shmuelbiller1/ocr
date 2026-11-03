"""Offline per-student CTC-head adaptation & regression-gated validation.

Adapted from the MIT-licensed ``mishkefet-app`` writer-adaptation reference
(Copyright (c) 2026 Itay Inbar, ``tools/model/adapter.py`` & ``spec/adapter.md``):

* The 30M ``Mishkefet-v1`` CNN + ViT encoder remains **completely frozen** and
  shared across all 50+ students in the school.
* Only the final linear CTC head (``W`` of shape ``198 × 512``, ``b`` of shape
  ``198``, ~400 KB in ``float32``) is adapted per student over cached encoder
  features using exact log-space forward–backward CTC loss, full-batch Adam,
  and L2 anchoring ``l2 * (||W - W0||^2 + ||b - b0||^2)`` toward the general
  ``Mishkefet-v1`` head ``(W0, b0)``.
* Every round is regression-gated against deterministic held-out verified lines
  (``FNV-1a(sample_id) % 8 == 0``): a round is accepted **only** if character
  error rate on held-out lines does not worsen.
* All persisted arrays use ``numpy.savez`` / ``numpy.load(..., allow_pickle=False)``
  — never ``pickle``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..training.store import (
    SchoolLearningStore,
    VerifiedLineSample,
    fnv1a_32,
    is_held_out_sample,
)

__all__ = [
    "AdaptConfig",
    "AdaptationReport",
    "ctc_loss_grad",
    "greedy_decode_logits",
    "load_writer_head_npz",
    "run_writer_training",
    "train_ctc_head",
    "train_writer_profile_in_process",
]

NEG_INF = -1e30
MAX_TRAIN_SAMPLES = 240


@dataclass(frozen=True)
class AdaptConfig:
    """Hyperparameters matching ``mishkefet-app`` ``spec/adapter.md``."""

    steps: int = 100
    lr: float = 1e-3
    l2: float = 0.1
    small_sample_l2: float = 0.25
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    aug_scales: tuple[float, ...] = (0.94, 1.06)


@dataclass(frozen=True)
class AdaptationReport:
    """Outcome of one per-student adaptation attempt."""

    writer_id: str
    writer_name: str
    accepted: bool
    active_round: int
    samples_total: int
    train_samples: int
    held_out_samples: int
    held_out_cer_before: float | None
    held_out_cer_after: float | None
    train_cer_before: float
    train_cer_after: float
    message: str

    def to_dict(self) -> dict:
        return {
            "writer_id": self.writer_id,
            "writer_name": self.writer_name,
            "accepted": bool(self.accepted),
            "active_round": int(self.active_round),
            "samples_total": int(self.samples_total),
            "train_samples": int(self.train_samples),
            "held_out_samples": int(self.held_out_samples),
            "held_out_cer_before": self.held_out_cer_before,
            "held_out_cer_after": self.held_out_cer_after,
            "train_cer_before": round(float(self.train_cer_before), 4),
            "train_cer_after": round(float(self.train_cer_after), 4),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AdaptationReport":
        return cls(
            writer_id=str(data["writer_id"]),
            writer_name=str(data.get("writer_name", "")),
            accepted=bool(data["accepted"]),
            active_round=int(data.get("active_round", 0)),
            samples_total=int(data.get("samples_total", 0)),
            train_samples=int(data.get("train_samples", 0)),
            held_out_samples=int(data.get("held_out_samples", 0)),
            held_out_cer_before=(
                float(data["held_out_cer_before"])
                if data.get("held_out_cer_before") is not None
                else None
            ),
            held_out_cer_after=(
                float(data["held_out_cer_after"])
                if data.get("held_out_cer_after") is not None
                else None
            ),
            train_cer_before=float(data.get("train_cer_before", 0.0)),
            train_cer_after=float(data.get("train_cer_after", 0.0)),
            message=str(data.get("message", "")),
        )


def _levenshtein(a: list[int] | str, b: list[int] | str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        ai = a[i - 1]
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def _log_softmax(z):
    import numpy as np

    m = z.max(axis=-1, keepdims=True)
    shifted = z - m
    return shifted - np.log(np.exp(shifted).sum(axis=-1, keepdims=True))


def _lse2(a, b):
    import numpy as np

    m = np.maximum(a, b)
    return np.where(
        m <= NEG_INF / 2.0,
        NEG_INF,
        m + np.log(np.exp(a - m) + np.exp(b - m)),
    )


def ctc_loss_grad(logits, label: list[int], blank: int = 0):
    """Exact log-space forward–backward CTC NLL and gradient w.r.t. ``logits``.

    Infeasible alignments (``label`` longer than ``T`` permits) return
    ``(0.0, zeros)``, matching PyTorch ``CTCLoss(zero_infinity=True)``.
    """
    import numpy as np

    def lse2(x, y):
        m = np.maximum(x, y)
        return np.where(
            m <= NEG_INF / 2.0,
            NEG_INF,
            m + np.log(np.exp(x - m) + np.exp(y - m)),
        )

    t_steps, n_classes = logits.shape
    if not label:
        return 0.0, np.zeros_like(logits, dtype=np.float32)

    lp = _log_softmax(logits.astype(np.float64))
    ext = [blank]
    for c in label:
        ext.append(int(c))
        ext.append(blank)
    s_len = len(ext)
    ext_arr = np.asarray(ext, dtype=np.int64)

    # Minimum required frames check before running DP
    repeats = sum(1 for i in range(1, len(label)) if label[i] == label[i - 1])
    if len(label) + repeats > t_steps:
        return 0.0, np.zeros_like(logits, dtype=np.float32)

    emit_lp = lp[:, ext_arr]
    skip = np.zeros(s_len, dtype=bool)
    skip[2:] = (ext_arr[2:] != blank) & (ext_arr[2:] != ext_arr[:-2])
    skip_tail = skip[2:]

    alpha = np.full((t_steps, s_len), NEG_INF, dtype=np.float64)
    alpha[0, 0] = emit_lp[0, 0]
    if s_len > 1:
        alpha[0, 1] = emit_lp[0, 1]
    for t in range(1, t_steps):
        prev = alpha[t - 1]
        a = prev.copy()
        a[1:] = lse2(a[1:], prev[:-1])
        a[2:] = np.where(skip_tail, lse2(a[2:], prev[:-2]), a[2:])
        alpha[t] = a + emit_lp[t]

    beta = np.full((t_steps, s_len), NEG_INF, dtype=np.float64)
    beta[t_steps - 1, s_len - 1] = 0.0
    if s_len > 1:
        beta[t_steps - 1, s_len - 2] = 0.0
    for t in range(t_steps - 2, -1, -1):
        nxt = beta[t + 1] + emit_lp[t + 1]
        b = nxt.copy()
        b[:-1] = lse2(b[:-1], nxt[1:])
        b[:-2] = np.where(skip_tail, lse2(b[:-2], nxt[2:]), b[:-2])
        beta[t] = b

    logz = alpha[t_steps - 1, s_len - 1]
    if s_len > 1:
        logz = float(lse2(np.asarray(logz), np.asarray(alpha[t_steps - 1, s_len - 2])))
    if logz <= NEG_INF / 2.0:
        return 0.0, np.zeros_like(logits, dtype=np.float32)

    post = np.exp(alpha + beta - logz)
    onehot = np.zeros((s_len, n_classes), dtype=np.float64)
    onehot[np.arange(s_len), ext_arr] = 1.0
    occ = post @ onehot
    grad = np.exp(lp) - occ
    return float(-logz), grad.astype(np.float32)


def greedy_decode_logits(logits, blank: int = 0) -> list[int]:
    """Collapse CTC argmax emissions into non-blank label indices."""
    import numpy as np

    best = np.argmax(logits, axis=-1).tolist()
    collapsed: list[int] = []
    prev = -1
    for idx in best:
        if idx != prev and idx != blank:
            collapsed.append(int(idx))
        prev = idx
    return collapsed


def evaluate_head_cer(W, b, eval_pairs: list[tuple[object, list[int]]]) -> float:
    """Compute corpus-level character error rate ``sum(ed) / sum(len(ref))``."""
    total_ed = 0
    total_len = 0
    for feat, target in eval_pairs:
        if not target:
            continue
        logits = feat @ W.T + b
        hyp = greedy_decode_logits(logits)
        total_ed += _levenshtein(hyp, target)
        total_len += len(target)
    return (total_ed / total_len) if total_len > 0 else 0.0


def train_ctc_head(
    W0,
    b0,
    train_pairs: list[tuple[object, list[int]]],
    cfg: AdaptConfig = AdaptConfig(),
    *,
    init_W=None,
    init_b=None,
):
    """Fit ``(W, b)`` with full-batch bias-corrected Adam & L2 toward ``(W0, b0)``."""
    import numpy as np

    w0_f = np.asarray(W0, dtype=np.float32)
    b0_f = np.asarray(b0, dtype=np.float32)
    W = np.asarray(init_W if init_W is not None else w0_f, dtype=np.float32).copy()
    b = np.asarray(init_b if init_b is not None else b0_f, dtype=np.float32).copy()
    if not train_pairs:
        return W, b

    eff_l2 = cfg.small_sample_l2 if len(train_pairs) < 8 else cfg.l2
    m_w = np.zeros_like(W)
    v_w = np.zeros_like(W)
    m_b = np.zeros_like(b)
    v_b = np.zeros_like(b)

    for step in range(1, cfg.steps + 1):
        gw = np.zeros_like(W)
        gb = np.zeros_like(b)
        valid_n = 0
        for feat, label in train_pairs:
            f32 = np.asarray(feat, dtype=np.float32)
            logits = f32 @ W.T + b
            loss, dz = ctc_loss_grad(logits, label)
            if loss == 0.0 and not dz.any():
                continue
            inv_len = 1.0 / max(1, len(label))
            dz_scaled = dz * inv_len
            gw += dz_scaled.T @ f32
            gb += dz_scaled.sum(axis=0)
            valid_n += 1
        if valid_n == 0:
            break
        gw = gw / valid_n + 2.0 * eff_l2 * (W - w0_f)
        gb = gb / valid_n + 2.0 * eff_l2 * (b - b0_f)

        m_w = cfg.beta1 * m_w + (1.0 - cfg.beta1) * gw
        v_w = cfg.beta2 * v_w + (1.0 - cfg.beta2) * (gw * gw)
        m_b = cfg.beta1 * m_b + (1.0 - cfg.beta1) * gb
        v_b = cfg.beta2 * v_b + (1.0 - cfg.beta2) * (gb * gb)

        b1_corr = 1.0 - (cfg.beta1 ** step)
        b2_corr = 1.0 - (cfg.beta2 ** step)
        W = (
            W - cfg.lr * (m_w / b1_corr) / (np.sqrt(v_w / b2_corr) + cfg.eps)
        ).astype(np.float32)
        b = (
            b - cfg.lr * (m_b / b1_corr) / (np.sqrt(v_b / b2_corr) + cfg.eps)
        ).astype(np.float32)

    return W, b


def save_writer_head_npz(path: Path, W, b) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=".npz", dir=str(path.parent), delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        np.savez(tmp_path, W=W.astype(np.float32), b=b.astype(np.float32))
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load_writer_head_npz(path: str | Path):
    """Load ``(W, b)`` safely with ``allow_pickle=False``."""
    import numpy as np

    with np.load(Path(path), allow_pickle=False) as archive:
        return (
            archive["W"].astype(np.float32, copy=True),
            archive["b"].astype(np.float32, copy=True),
        )


def _split_train_and_holdout(
    samples: list[VerifiedLineSample],
) -> tuple[list[VerifiedLineSample], list[VerifiedLineSample]]:
    """Split verified lines deterministically into training and held-out sets."""
    if len(samples) < 6:
        return list(samples[-MAX_TRAIN_SAMPLES:]), []
    held_out = [s for s in samples if is_held_out_sample(s.sample_id)]
    train = [s for s in samples if not is_held_out_sample(s.sample_id)]
    if not held_out:
        # Deterministic fallback when none of >=6 samples hit hash % 8 == 0
        chosen = min(samples, key=lambda s: (fnv1a_32(s.sample_id) % 8, s.sample_id))
        held_out = [chosen]
        train = [s for s in samples if s.sample_id != chosen.sample_id]
    if not train and held_out:
        train = [held_out.pop(0)]
    return train[-MAX_TRAIN_SAMPLES:], held_out


def _scale_width(im: Image.Image, scale: float) -> Image.Image:
    if abs(scale - 1.0) < 1e-3:
        return im
    new_w = max(16, int(round(im.width * scale)))
    return im.resize((new_w, im.height), Image.Resampling.BILINEAR)


def _load_or_extract_sample_features(
    recognizer,
    store: SchoolLearningStore,
    sample: VerifiedLineSample,
    model_sha256: str,
    aug_scales: tuple[float, ...],
):
    """Return ``(plain_feat, [aug_feat, ...])`` float32 arrays, caching on disk."""
    import numpy as np

    feat_dir = store.writer_dir(sample.writer_id) / "features"
    feat_dir.mkdir(parents=True, exist_ok=True)
    cache_file = feat_dir / f"{sample.sample_id}--{model_sha256[:12]}.npz"
    if cache_file.is_file():
        try:
            with np.load(cache_file, allow_pickle=False) as data:
                plain = data["plain"].astype(np.float32)
                n_aug = int(data["n_aug"][0])
                augs = [data[f"aug_{i}"].astype(np.float32) for i in range(n_aug)]
                return plain, augs
        except Exception:
            cache_file.unlink(missing_ok=True)

    img_path = store.root.joinpath(*sample.image_relpath.split("/")).resolve()
    with Image.open(img_path) as raw_im:
        im = raw_im.convert("RGB")
        views = [im] + [_scale_width(im, sc) for sc in aug_scales]
    extracted = recognizer.extract_line_features(views)
    plain_f = extracted[0].astype(np.float32)
    aug_fs = [arr.astype(np.float32) for arr in extracted[1:]]

    save_dict = {
        "plain": plain_f.astype(np.float16),
        "n_aug": np.asarray([len(aug_fs)], dtype=np.int32),
    }
    for idx, arr in enumerate(aug_fs):
        save_dict[f"aug_{idx}"] = arr.astype(np.float16)
    np.savez(cache_file, **save_dict)
    return plain_f, aug_fs


def train_writer_profile_in_process(
    writer_id: str,
    model_path: str | Path,
    store_root: str | Path | None = None,
    cfg: AdaptConfig = AdaptConfig(),
    recognizer_factory=None,
) -> AdaptationReport:
    """Adapt a student's CTC head in-process using verified diplomatic lines."""
    from .models import MODEL_ARTIFACTS, verify_file

    if recognizer_factory is None:
        from .vendor.hebocr.recognize import Recognizer

        recognizer_factory = lambda path: Recognizer(str(path), device="cpu")

    store = SchoolLearningStore(store_root)
    profile = store.get_writer(writer_id)
    if profile is None:
        raise ValueError(f"לא נמצא פרופיל תלמיד עבור {writer_id!r}.")

    model_file = Path(model_path)
    artifact = MODEL_ARTIFACTS.get("mishkefet-v1")
    if artifact is not None:
        problem = verify_file(model_file, artifact)
        if problem is not None:
            raise RuntimeError(
                f"קובץ המודל של Mishkefet נכשל בבדיקת שלמות ({problem})."
            )
        model_sha256 = artifact.sha256
    else:
        model_sha256 = hashlib.sha256(model_file.read_bytes()).hexdigest()

    samples = store.list_writer_samples(profile.writer_id)
    if not samples:
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=False,
            active_round=profile.active_round,
            samples_total=0,
            train_samples=0,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message="אין עדיין שורות מאומתות עבור תלמיד זה.",
        )

    recognizer = recognizer_factory(model_file)
    W0, b0 = recognizer.base_head_numpy()

    # Load previous accepted head if compatible with this checkpoint
    prev_head_path = store.active_head_path(
        profile.writer_id, model_sha256=model_sha256
    )
    if prev_head_path is not None:
        W_prev, b_prev = load_writer_head_npz(prev_head_path)
    else:
        W_prev, b_prev = W0.copy(), b0.copy()

    train_samples, held_out_samples = _split_train_and_holdout(samples)
    train_plain_pairs: list[tuple[object, list[int]]] = []
    train_fit_pairs: list[tuple[object, list[int]]] = []
    held_out_pairs: list[tuple[object, list[int]]] = []

    use_aug = cfg.aug_scales if len(train_samples) < 64 else ()
    for sample in train_samples:
        label = recognizer.charset.encode(sample.diplomatic_text)
        if not label:
            continue
        plain_f, aug_fs = _load_or_extract_sample_features(
            recognizer, store, sample, model_sha256, use_aug
        )
        train_plain_pairs.append((plain_f, label))
        train_fit_pairs.append((plain_f, label))
        for af in aug_fs:
            train_fit_pairs.append((af, label))

    for sample in held_out_samples:
        label = recognizer.charset.encode(sample.diplomatic_text)
        if not label:
            continue
        plain_f, _ = _load_or_extract_sample_features(
            recognizer, store, sample, model_sha256, ()
        )
        held_out_pairs.append((plain_f, label))

    if not train_fit_pairs:
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=False,
            active_round=profile.active_round,
            samples_total=len(samples),
            train_samples=0,
            held_out_samples=len(held_out_pairs),
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message="לא נמצאו תווים ברי-אימון בשורות שאומתו.",
        )

    train_cer_before = evaluate_head_cer(W_prev, b_prev, train_plain_pairs)
    held_cer_before = (
        evaluate_head_cer(W_prev, b_prev, held_out_pairs)
        if held_out_pairs
        else None
    )

    W_new, b_new = train_ctc_head(W0, b0, train_fit_pairs, cfg=cfg)
    train_cer_after = evaluate_head_cer(W_new, b_new, train_plain_pairs)
    held_cer_after = (
        evaluate_head_cer(W_new, b_new, held_out_pairs)
        if held_out_pairs
        else None
    )

    if held_out_pairs:
        # Regression gate: accept iff held-out CER does not worsen (vs previous OR general)
        base_held_cer = evaluate_head_cer(W0, b0, held_out_pairs)
        ref_cer = min(held_cer_before, base_held_cer)  # type: ignore[type-var]
        accepted = held_cer_after <= ref_cer + 1e-6  # type: ignore[operator]
    else:
        base_train_cer = evaluate_head_cer(W0, b0, train_plain_pairs)
        ref_train_cer = min(train_cer_before, base_train_cer)
        accepted = train_cer_after <= ref_train_cer + 1e-6

    if accepted:
        new_round = int(profile.active_round) + 1
        heads_dir = store.writer_dir(profile.writer_id) / "heads"
        round_path = heads_dir / f"head-r{new_round:04d}.npz"
        save_writer_head_npz(round_path, W_new, b_new)
        save_writer_head_npz(store.writer_head_path(profile.writer_id), W_new, b_new)
        meta = {
            "writer_id": profile.writer_id,
            "writer_name": profile.name,
            "round": new_round,
            "model_sha256": model_sha256,
            "samples_total": len(samples),
            "train_samples": len(train_plain_pairs),
            "held_out_samples": len(held_out_pairs),
            "held_out_cer_before": (
                round(held_cer_before, 4) if held_cer_before is not None else None
            ),
            "held_out_cer_after": (
                round(held_cer_after, 4) if held_cer_after is not None else None
            ),
            "train_cer_before": round(train_cer_before, 4),
            "train_cer_after": round(train_cer_after, 4),
        }
        store.writer_head_meta_path(profile.writer_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        store.update_writer_training_metadata(
            profile.writer_id,
            active_round=new_round,
            model_sha256=model_sha256,
            held_out_cer_before=meta["held_out_cer_before"],
            held_out_cer_after=meta["held_out_cer_after"],
        )
        msg = (
            f"פרופיל כתב-היד של {profile.name} עודכן (סיבוב #{new_round}, "
            f"{len(samples)} שורות מאומתות)."
        )
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=True,
            active_round=new_round,
            samples_total=len(samples),
            train_samples=len(train_plain_pairs),
            held_out_samples=len(held_out_pairs),
            held_out_cer_before=held_cer_before,
            held_out_cer_after=held_cer_after,
            train_cer_before=train_cer_before,
            train_cer_after=train_cer_after,
            message=msg,
        )

    # Keep previous head intact when regression gate rejects update; still sync sample count
    store.update_writer_training_metadata(
        profile.writer_id,
        active_round=profile.active_round,
        model_sha256=model_sha256,
        held_out_cer_before=profile.held_out_cer_before,
        held_out_cer_after=profile.held_out_cer_after,
    )
    msg = (
        f"השורות נשמרו במאגר ({len(samples)} שורות), אך המודל הקודם נשמר "
        "כדי למנוע ירידה בדיוק על שורות הבקרה. הוסיפו עוד כמה שורות מאומתות ונסו שוב."
    )
    return AdaptationReport(
        writer_id=profile.writer_id,
        writer_name=profile.name,
        accepted=False,
        active_round=profile.active_round,
        samples_total=len(samples),
        train_samples=len(train_plain_pairs),
        held_out_samples=len(held_out_pairs),
        held_out_cer_before=held_cer_before,
        held_out_cer_after=held_cer_after,
        train_cer_before=train_cer_before,
        train_cer_after=train_cer_after,
        message=msg,
    )


def run_writer_training(
    writer_id: str,
    *,
    model_path: str | Path | None = None,
    store_root: str | Path | None = None,
    timeout_seconds: float = 300.0,
) -> AdaptationReport:
    """Adapt a student's profile either in-process or via ``ocr-worker.exe``."""
    from .mishkefet import mishkefet_importable
    from .models import MODEL_ARTIFACTS, models_directory
    from .worker import worker_path

    resolved_model = Path(model_path) if model_path is not None else None
    if resolved_model is None:
        art = MODEL_ARTIFACTS.get("mishkefet-v1")
        if art is not None:
            cand = models_directory() / art.filename
            if cand.is_file():
                resolved_model = cand
    if resolved_model is None or not resolved_model.is_file():
        store = SchoolLearningStore(store_root)
        prof = store.get_writer(writer_id)
        samples_n = len(store.list_writer_samples(writer_id)) if prof else 0
        return AdaptationReport(
            writer_id=writer_id,
            writer_name=prof.name if prof else writer_id,
            accepted=False,
            active_round=prof.active_round if prof else 0,
            samples_total=samples_n,
            train_samples=0,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message=(
                f"השורות המאומתות נשמרו במאגר ({samples_n} שורות). "
                "כדי לאמן פרופיל אישי יש להתקין את מודל Mishkefet-v1."
            ),
        )

    if mishkefet_importable():
        return train_writer_profile_in_process(
            writer_id, resolved_model, store_root=store_root
        )

    w_exe = worker_path()
    if w_exe is None or not w_exe.is_file():
        store = SchoolLearningStore(store_root)
        prof = store.get_writer(writer_id)
        samples_n = len(store.list_writer_samples(writer_id)) if prof else 0
        return AdaptationReport(
            writer_id=writer_id,
            writer_name=prof.name if prof else writer_id,
            accepted=False,
            active_round=prof.active_round if prof else 0,
            samples_total=samples_n,
            train_samples=0,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message=(
                f"השורות המאומתות נשמרו במאגר ({samples_n} שורות). "
                "רכיב העובד (ocr-worker) לא נמצא לאימון מקומי."
            ),
        )

    eff_store = SchoolLearningStore(store_root)
    with tempfile.TemporaryDirectory(prefix="ocr-train-") as td:
        job_file = Path(td) / "train-job.json"
        res_file = Path(td) / "train-result.json"
        job_file.write_text(
            json.dumps(
                {
                    "writer_id": writer_id,
                    "model_path": str(resolved_model),
                    "learning_dir": str(eff_store.root),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                str(w_exe),
                "--train-writer",
                str(job_file),
                "--result",
                str(res_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        if not res_file.is_file():
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"אימון פרופיל הכותב נכשל ({proc.returncode}): {err}"
            )
        payload = json.loads(res_file.read_text(encoding="utf-8"))
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        return AdaptationReport.from_dict(payload)
