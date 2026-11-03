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
    split_writer_train_and_holdout,
)

__all__ = [
    "AdaptConfig",
    "AdaptationReport",
    "ctc_loss_grad",
    "greedy_decode_logits",
    "import_external_adapter_in_process",
    "import_external_adapter_npz",
    "load_writer_head_npz",
    "run_writer_training",
    "train_ctc_head",
    "train_writer_profile_in_process",
]

NEG_INF = -1e30
MAX_TRAIN_SAMPLES = 240
MIN_VERIFIED_FOR_ADAPT = 8
MIN_HELDOUT_SAMPLES = 2
MIN_HELDOUT_CHARS = 12


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
    status: str = "kept_previous"
    held_out_chars: int = 0
    held_out_wer_before: float | None = None
    held_out_wer_after: float | None = None

    def to_dict(self) -> dict:
        return {
            "writer_id": self.writer_id,
            "writer_name": self.writer_name,
            "accepted": bool(self.accepted),
            "status": self.status,
            "active_round": int(self.active_round),
            "samples_total": int(self.samples_total),
            "train_samples": int(self.train_samples),
            "held_out_samples": int(self.held_out_samples),
            "held_out_chars": int(self.held_out_chars),
            "held_out_cer_before": self.held_out_cer_before,
            "held_out_cer_after": self.held_out_cer_after,
            "held_out_wer_before": self.held_out_wer_before,
            "held_out_wer_after": self.held_out_wer_after,
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
            status=str(
                data.get(
                    "status",
                    "accepted" if data.get("accepted") else "kept_previous",
                )
            ),
            active_round=int(data.get("active_round", 0)),
            samples_total=int(data.get("samples_total", 0)),
            train_samples=int(data.get("train_samples", 0)),
            held_out_samples=int(data.get("held_out_samples", 0)),
            held_out_chars=int(data.get("held_out_chars", 0)),
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
            held_out_wer_before=(
                float(data["held_out_wer_before"])
                if data.get("held_out_wer_before") is not None
                else None
            ),
            held_out_wer_after=(
                float(data["held_out_wer_after"])
                if data.get("held_out_wer_after") is not None
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


def evaluate_head_detailed(
    W,
    b,
    eval_pairs: list[tuple[object, list[int]]],
    charset=None,
) -> dict[str, float | int]:
    """Compute CER, WER, character count, and mean normalized CTC NLL on ``eval_pairs``."""
    total_char_ed = 0
    total_chars = 0
    total_word_ed = 0
    total_words = 0
    total_nll = 0.0
    n_valid = 0
    for feat, target in eval_pairs:
        if not target:
            continue
        logits = feat @ W.T + b
        hyp = greedy_decode_logits(logits)
        total_char_ed += _levenshtein(hyp, target)
        total_chars += len(target)
        loss, _ = ctc_loss_grad(logits, target)
        total_nll += loss / max(1, len(target))
        n_valid += 1
        if charset is not None:
            ref_words = charset.decode(target).split()
            hyp_words = charset.decode(hyp).split()
            if ref_words:
                total_word_ed += _levenshtein(hyp_words, ref_words)
                total_words += len(ref_words)
    return {
        "cer": (total_char_ed / total_chars) if total_chars > 0 else 0.0,
        "wer": (total_word_ed / total_words) if total_words > 0 else 0.0,
        "chars": total_chars,
        "words": total_words,
        "nll": (total_nll / n_valid) if n_valid > 0 else 0.0,
    }


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
            if abs(loss) <= 1e-12 and not dz.any():
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
    """Split verified lines into strictly disjoint train and held-out sets."""
    return split_writer_train_and_holdout(
        samples,
        min_verified_for_adapt=MIN_VERIFIED_FOR_ADAPT,
        min_heldout_samples=MIN_HELDOUT_SAMPLES,
        max_train_samples=MAX_TRAIN_SAMPLES,
    )


def _split_for_external_import(
    samples: list[VerifiedLineSample],
    exported_train_ids: set[str],
) -> tuple[list[VerifiedLineSample], list[VerifiedLineSample]]:
    """Select an unseen held-out set for externally trained ``.npz`` adapters.

    Guarantees that no sample previously emitted into ``train.jsonl`` for this
    writer is ever included in ``held_out_samples``, even when additional pages
    were verified between export and import.
    """
    base_train, base_held = _split_train_and_holdout(samples)
    if not exported_train_ids:
        return base_train, base_held

    clean_held = [s for s in base_held if s.sample_id not in exported_train_ids]
    held_ids = {s.sample_id for s in clean_held}
    target_hold = max(MIN_HELDOUT_SAMPLES, int(round(0.20 * len(samples))))

    if len(clean_held) < target_hold:
        unseen_candidates = [
            s
            for s in samples
            if s.sample_id not in exported_train_ids and s.sample_id not in held_ids
        ]
        by_page: dict[tuple[str, int], list[VerifiedLineSample]] = {}
        for s in unseen_candidates:
            by_page.setdefault((s.document_key, s.page_number), []).append(s)
        ranked_pages = sorted(
            by_page.keys(),
            key=lambda pg: (
                fnv1a_32(
                    f"{unseen_candidates[0].writer_id}:{pg[0]}:{pg[1]}"
                )
                % 8,
                pg,
            ),
        )
        for pg in ranked_pages:
            for s in by_page[pg]:
                clean_held.append(s)
                held_ids.add(s.sample_id)
            if len(clean_held) >= target_hold:
                break

    train_out = [s for s in samples if s.sample_id not in held_ids]
    return train_out[-MAX_TRAIN_SAMPLES:], clean_held


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
    if artifact is None:
        raise RuntimeError("הגדרת המודל mishkefet-v1 אינה זמינה.")
    problem = verify_file(model_file, artifact)
    if problem is not None:
        raise RuntimeError(
            f"קובץ המודל של Mishkefet נכשל בבדיקת שלמות ({problem})."
        )
    model_sha256 = artifact.sha256

    samples = store.list_writer_samples(profile.writer_id)
    if not samples:
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=False,
            status="no_samples",
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

    if len(samples) < MIN_VERIFIED_FOR_ADAPT:
        needed = MIN_VERIFIED_FOR_ADAPT - len(samples)
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=False,
            status="insufficient_evidence",
            active_round=profile.active_round,
            samples_total=len(samples),
            train_samples=len(samples),
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message=(
                f"נשמרו {len(samples)} שורות מאומתות עבור {profile.name}. "
                f"עדיין אין מספיק דוגמאות להוכחת שיפור מובהק (נדרשות עוד {needed} שורות "
                f"מאומתות כדי להגיע ל-{MIN_VERIFIED_FOR_ADAPT} שורות כולל קבוצת בקרה נפרדת). "
                "מודל הבסיס/הקודם נשאר פעיל."
            ),
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

    held_chars = sum(len(lbl) for _, lbl in held_out_pairs)
    if (
        not train_fit_pairs
        or len(held_out_pairs) < MIN_HELDOUT_SAMPLES
        or held_chars < MIN_HELDOUT_CHARS
    ):
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=False,
            status="insufficient_evidence",
            active_round=profile.active_round,
            samples_total=len(samples),
            train_samples=len(train_plain_pairs),
            held_out_samples=len(held_out_pairs),
            held_out_chars=held_chars,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message=(
                f"נשמרו {len(samples)} שורות מאומתות, אך קבוצת הבקרה הנפרדת עדיין קטנה מדי "
                "להוכחת שיפור מהימנה. הוסיפו עוד מספר שורות מאומתות."
            ),
        )

    charset = getattr(recognizer, "charset", None)
    train_cer_before = evaluate_head_cer(W_prev, b_prev, train_plain_pairs)
    prev_held = evaluate_head_detailed(W_prev, b_prev, held_out_pairs, charset)
    base_held = evaluate_head_detailed(W0, b0, held_out_pairs, charset)
    held_cer_before = float(prev_held["cer"])
    held_wer_before = float(prev_held["wer"])

    candidate_runs: list[tuple[list[tuple[object, list[int]]], AdaptConfig]] = [
        (train_fit_pairs, cfg)
    ]
    if len(train_plain_pairs) < 48 and cfg.steps > 45:
        candidate_runs.append(
            (
                train_fit_pairs,
                AdaptConfig(
                    steps=45,
                    lr=cfg.lr,
                    l2=max(0.45, cfg.l2),
                    small_sample_l2=max(0.45, cfg.small_sample_l2),
                    beta1=cfg.beta1,
                    beta2=cfg.beta2,
                    eps=cfg.eps,
                    aug_scales=cfg.aug_scales,
                ),
            )
        )
        candidate_runs.append(
            (
                train_plain_pairs,
                AdaptConfig(
                    steps=35,
                    lr=min(5e-4, cfg.lr),
                    l2=max(1.0, cfg.l2),
                    small_sample_l2=max(1.0, cfg.small_sample_l2),
                    beta1=cfg.beta1,
                    beta2=cfg.beta2,
                    eps=cfg.eps,
                    aug_scales=(),
                ),
            )
        )

    best_tuple: tuple[float, float, float] | None = None
    W_new, b_new = W_prev, b_prev
    cand_held: dict[str, float | int] = prev_held
    for c_pairs, c_cfg in candidate_runs:
        w_cand, b_cand = train_ctc_head(W0, b0, c_pairs, cfg=c_cfg)
        h_eval = evaluate_head_detailed(w_cand, b_cand, held_out_pairs, charset)
        score_key = (
            round(float(h_eval["cer"]), 6),
            round(float(h_eval["wer"]), 6),
            round(float(h_eval["nll"]), 6),
        )
        if best_tuple is None or score_key < best_tuple:
            best_tuple = score_key
            W_new, b_new = w_cand, b_cand
            cand_held = h_eval

    train_cer_after = evaluate_head_cer(W_new, b_new, train_plain_pairs)
    held_cer_after = float(cand_held["cer"])
    held_wer_after = float(cand_held["wer"])

    ref_cer = min(held_cer_before, float(base_held["cer"]))
    ref_nll = min(float(prev_held["nll"]), float(base_held["nll"]))
    # Accept ONLY when independent held-out evaluation proves improvement
    cer_improved = held_cer_after < (ref_cer - 1e-6)
    tied_better_calibrated = (
        abs(held_cer_after - ref_cer) <= 1e-6
        and held_cer_after < (float(base_held["cer"]) - 1e-6)
        and float(cand_held["nll"]) < (ref_nll - 0.02)
        and held_wer_after <= (held_wer_before + 1e-6)
    )
    accepted = bool(cer_improved or tied_better_calibrated)

    if accepted:
        existing_rounds = [
            v.round_number for v in store.list_adapter_versions(profile.writer_id)
        ]
        new_round = max([int(profile.active_round), *existing_rounds], default=0) + 1
        rel_head = f"writers/{profile.writer_id}/heads/head-r{new_round:04d}.npz"
        round_path = store.root.joinpath(*rel_head.split("/"))
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
            "held_out_chars": held_chars,
            "held_out_cer_before": round(held_cer_before, 4),
            "held_out_cer_after": round(held_cer_after, 4),
            "held_out_wer_before": round(held_wer_before, 4),
            "held_out_wer_after": round(held_wer_after, 4),
            "train_cer_before": round(train_cer_before, 4),
            "train_cer_after": round(train_cer_after, 4),
        }
        store.writer_head_meta_path(profile.writer_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        store.record_adapter_version(
            profile.writer_id,
            round_number=new_round,
            head_relpath=rel_head,
            model_sha256=model_sha256,
            samples_total=len(samples),
            train_samples=len(train_plain_pairs),
            held_out_samples=len(held_out_pairs),
            held_out_chars=held_chars,
            held_out_cer_before=meta["held_out_cer_before"],
            held_out_cer_after=meta["held_out_cer_after"],
            held_out_wer_before=meta["held_out_wer_before"],
            held_out_wer_after=meta["held_out_wer_after"],
            activate=True,
        )
        msg = (
            f"הוכח שיפור בשורות הבקרה הנפרדות עבור {profile.name} "
            f"(שגיאת תווים ירדה מ-{held_cer_before * 100:.1f}% ל-{held_cer_after * 100:.1f}% "
            f"על {len(held_out_pairs)} שורות בקרה) — הופעלה גרסה #{new_round}."
        )
        return AdaptationReport(
            writer_id=profile.writer_id,
            writer_name=profile.name,
            accepted=True,
            status="accepted",
            active_round=new_round,
            samples_total=len(samples),
            train_samples=len(train_plain_pairs),
            held_out_samples=len(held_out_pairs),
            held_out_chars=held_chars,
            held_out_cer_before=held_cer_before,
            held_out_cer_after=held_cer_after,
            held_out_wer_before=held_wer_before,
            held_out_wer_after=held_wer_after,
            train_cer_before=train_cer_before,
            train_cer_after=train_cer_after,
            message=msg,
        )

    msg = (
        f"השורות המאומתות נשמרו ({len(samples)} שורות), אך העדכון לא שיפר את הדיוק "
        f"על שורות הבקרה העצמאיות ({held_cer_before * 100:.1f}% לפני לעומת "
        f"{held_cer_after * 100:.1f}% בניסיון) — לכן נשמר המודל הקודם ללא שינוי."
    )
    return AdaptationReport(
        writer_id=profile.writer_id,
        writer_name=profile.name,
        accepted=False,
        status="kept_previous",
        active_round=profile.active_round,
        samples_total=len(samples),
        train_samples=len(train_plain_pairs),
        held_out_samples=len(held_out_pairs),
        held_out_chars=held_chars,
        held_out_cer_before=held_cer_before,
        held_out_cer_after=held_cer_after,
        held_out_wer_before=held_wer_before,
        held_out_wer_after=held_wer_after,
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

    clean_wid = (writer_id or "").strip()
    store = SchoolLearningStore(store_root)
    if not clean_wid:
        gen_n = len(store.list_writer_samples(""))
        return AdaptationReport(
            writer_id="",
            writer_name="כללי / לא ידוע",
            accepted=False,
            status="general_profile",
            active_round=0,
            samples_total=gen_n,
            train_samples=0,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message=(
                f"השורות נשמרו תחת 'כללי / לא ידוע' ({gen_n} שורות מאומתות) וזמינות לייצוא. "
                "להתאמה אישית בחרו פרופיל תלמיד ספציפי."
            ),
        )

    prof = store.get_writer(clean_wid)
    samples_n = len(store.list_writer_samples(clean_wid)) if prof else 0
    if prof is not None and samples_n < MIN_VERIFIED_FOR_ADAPT:
        needed = MIN_VERIFIED_FOR_ADAPT - samples_n
        return AdaptationReport(
            writer_id=clean_wid,
            writer_name=prof.name,
            accepted=False,
            status="insufficient_evidence",
            active_round=prof.active_round,
            samples_total=samples_n,
            train_samples=samples_n,
            held_out_samples=0,
            held_out_cer_before=None,
            held_out_cer_after=None,
            train_cer_before=0.0,
            train_cer_after=0.0,
            message=(
                f"נשמרו {samples_n} שורות מאומתות עבור {prof.name}. "
                f"עדיין אין מספיק דוגמאות להוכחת שיפור מובהק (נדרשות עוד {needed} שורות "
                f"מאומתות כדי להגיע ל-{MIN_VERIFIED_FOR_ADAPT} שורות כולל קבוצת בקרה נפרדת). "
                "מודל הבסיס/הקודם נשאר פעיל."
            ),
        )

    resolved_model = Path(model_path) if model_path is not None else None
    if resolved_model is None:
        art = MODEL_ARTIFACTS.get("mishkefet-v1")
        if art is not None:
            cand = models_directory() / art.filename
            if cand.is_file():
                resolved_model = cand
    if resolved_model is None or not resolved_model.is_file():
        return AdaptationReport(
            writer_id=clean_wid,
            writer_name=prof.name if prof else clean_wid,
            accepted=False,
            status="unavailable",
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
            clean_wid, resolved_model, store_root=store_root
        )

    w_exe = worker_path()
    if w_exe is None or not w_exe.is_file():
        return AdaptationReport(
            writer_id=clean_wid,
            writer_name=prof.name if prof else clean_wid,
            accepted=False,
            status="unavailable",
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


def _validate_npz_head_pure_python(
    npz_path: Path,
    *,
    expected_vocab_size: int = 198,
    expected_feat_dim: int = 512,
) -> None:
    """Verify ``W`` and ``b`` ``.npy`` arrays inside ``npz_path`` without pickle."""
    import ast
    import struct
    import zipfile

    try:
        zf_ctx = zipfile.ZipFile(npz_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("קובץ המתאם (.npz) לא נמצא או שאינו ארכיון תקין.") from exc

    with zf_ctx as zf:
        names = set(zf.namelist())
        if not {"W.npy", "b.npy"}.issubset(names):
            raise ValueError("קובץ ה-.npz חייב להכיל מערכי W.npy ו-b.npy.")
        for member, exp_shape in (
            ("W.npy", (expected_vocab_size, expected_feat_dim)),
            ("b.npy", (expected_vocab_size,)),
        ):
            raw = zf.read(member)
            if len(raw) < 10 or raw[:6] != b"\x93NUMPY":
                raise ValueError(f"פורמט {member} אינו מערך NumPy תקין.")
            major = raw[6]
            if major == 1:
                hdr_len = struct.unpack("<H", raw[8:10])[0]
                hdr_end = 10 + hdr_len
            elif major in (2, 3):
                hdr_len = struct.unpack("<I", raw[8:12])[0]
                hdr_end = 12 + hdr_len
            else:
                raise ValueError(f"גרסת מערך NumPy אינה נתמכת ({major}).")
            header = ast.literal_eval(
                raw[hdr_end - hdr_len : hdr_end].decode("latin1").strip()
            )
            if not isinstance(header, dict):
                raise ValueError(f"כותרת {member} אינה תקינה.")
            descr = str(header.get("descr", ""))
            if descr not in ("<f4", "|f4", "f4"):
                raise ValueError(
                    f"סוג נתונים לא בטוח או לא נתמך ב-{member} ({descr!r}); נדרש float32 ללא pickle."
                )
            if bool(header.get("fortran_order", False)):
                raise ValueError(f"מערך {member} חייב להיות ברצף C רגיל.")
            shape = tuple(int(x) for x in header.get("shape", ()))
            if shape != exp_shape:
                raise ValueError(
                    f"ממדי {member} ({shape}) אינם תואמים למודל Mishkefet-v1 ({exp_shape})."
                )
            n_elems = 1
            for dim in shape:
                n_elems *= dim
            if len(raw) - hdr_end != n_elems * 4:
                raise ValueError(f"אורך הנתונים הבינאריים ב-{member} שגוי.")


def _store_inactive_imported_head(
    store: SchoolLearningStore,
    profile,
    src: Path,
    *,
    model_sha256: str,
    samples_total: int,
    status: str,
    message: str,
    **metrics,
) -> AdaptationReport:
    import shutil

    existing_rounds = [
        v.round_number for v in store.list_adapter_versions(profile.writer_id)
    ]
    new_round = max([int(profile.active_round), *existing_rounds], default=0) + 1
    rel_head = f"writers/{profile.writer_id}/heads/head-r{new_round:04d}.npz"
    round_path = store.root.joinpath(*rel_head.split("/"))
    round_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, round_path)
    h_before = metrics.get("held_out_cer_before")
    h_after = metrics.get("held_out_cer_after")
    hw_before = metrics.get("held_out_wer_before")
    hw_after = metrics.get("held_out_wer_after")
    store.record_adapter_version(
        profile.writer_id,
        round_number=new_round,
        head_relpath=rel_head,
        model_sha256=model_sha256,
        samples_total=samples_total,
        train_samples=int(metrics.get("train_samples", 0)),
        held_out_samples=int(metrics.get("held_out_samples", 0)),
        held_out_chars=int(metrics.get("held_out_chars", 0)),
        held_out_cer_before=round(h_before, 4) if h_before is not None else None,
        held_out_cer_after=round(h_after, 4) if h_after is not None else None,
        held_out_wer_before=round(hw_before, 4) if hw_before is not None else None,
        held_out_wer_after=round(hw_after, 4) if hw_after is not None else None,
        activate=False,
    )
    return AdaptationReport(
        writer_id=profile.writer_id,
        writer_name=profile.name,
        accepted=False,
        status=status,
        active_round=profile.active_round,
        samples_total=samples_total,
        train_samples=int(metrics.get("train_samples", 0)),
        held_out_samples=int(metrics.get("held_out_samples", 0)),
        held_out_chars=int(metrics.get("held_out_chars", 0)),
        held_out_cer_before=h_before,
        held_out_cer_after=h_after,
        held_out_wer_before=hw_before,
        held_out_wer_after=hw_after,
        train_cer_before=0.0,
        train_cer_after=0.0,
        message=message,
    )


def import_external_adapter_in_process(
    writer_id: str,
    npz_path: str | Path,
    *,
    store_root: str | Path | None = None,
    model_path: str | Path | None = None,
    recognizer_factory=None,
    expected_vocab_size: int = 198,
    expected_feat_dim: int = 512,
) -> AdaptationReport:
    """In-process validation & held-out evaluation of an external ``.npz`` head."""
    import shutil
    from .models import MODEL_ARTIFACTS, models_directory, verify_file

    src = Path(npz_path)
    _validate_npz_head_pure_python(
        src,
        expected_vocab_size=expected_vocab_size,
        expected_feat_dim=expected_feat_dim,
    )
    try:
        load_writer_head_npz(src)
    except ImportError:
        pass

    store = SchoolLearningStore(store_root)
    profile = store.get_writer(writer_id)
    if profile is None:
        raise KeyError(f"לא נמצא פרופיל תלמיד עבור {writer_id!r}.")

    art = MODEL_ARTIFACTS.get("mishkefet-v1")
    model_sha256 = art.sha256 if art is not None else ""
    samples = store.list_writer_samples(profile.writer_id)

    def _store_inactive(status: str, message: str, **metrics) -> AdaptationReport:
        return _store_inactive_imported_head(
            store,
            profile,
            src,
            model_sha256=model_sha256,
            samples_total=len(samples),
            status=status,
            message=message,
            **metrics,
        )

    if len(samples) < MIN_VERIFIED_FOR_ADAPT:
        needed = MIN_VERIFIED_FOR_ADAPT - len(samples)
        return _store_inactive(
            "insufficient_evidence",
            (
                f"קובץ ה-.npz אומת ללא pickle ונשמר כגרסה לא-פעילה עבור {profile.name}, "
                f"אך לא הופעל משום שנדרשות עוד {needed} שורות מאומתות (לפחות {MIN_VERIFIED_FOR_ADAPT} סה״כ) "
                "כדי להוכיח שיפור על קבוצת בקרה עצמאית."
            ),
        )

    m_path = (
        Path(model_path)
        if model_path is not None
        else models_directory() / (art.filename if art else "mishkefet-v1.pt")
    )

    if recognizer_factory is None:
        from .mishkefet import mishkefet_importable

        if not m_path.is_file() or not mishkefet_importable():
            return _store_inactive(
                "insufficient_evidence",
                (
                    f"קובץ ה-.npz אומת ונשמר כגרסה לא-פעילה עבור {profile.name} "
                    "(קובץ המודל או מנוע Mishkefet אינם מותקנים עדיין לבדיקת קבוצת הבקרה)."
                ),
            )
        if art is not None:
            prob = verify_file(m_path, art)
            if prob is not None:
                raise RuntimeError(f"קובץ המודל אינו תקין: {prob}")
        from .vendor.hebocr.recognize import Recognizer

        recognizer = Recognizer(str(m_path), device="cpu")
    else:
        recognizer = recognizer_factory(m_path)

    W0, b0 = recognizer.base_head_numpy()
    W_imp, b_imp = load_writer_head_npz(src)
    prev_head = store.active_head_path(profile.writer_id, model_sha256=model_sha256)
    if prev_head is not None:
        try:
            W_prev, b_prev = load_writer_head_npz(prev_head)
        except Exception:
            W_prev, b_prev = W0.copy(), b0.copy()
    else:
        W_prev, b_prev = W0.copy(), b0.copy()

    exported_train_ids = store.exported_training_sample_ids(profile.writer_id)
    train_samples, held_out_samples = _split_for_external_import(
        samples, exported_train_ids
    )
    held_out_pairs: list[tuple[object, list[int]]] = []
    held_chars = 0
    for s in held_out_samples:
        lbl = recognizer.charset.encode(s.diplomatic_text)
        if not lbl:
            continue
        plain_f, _ = _load_or_extract_sample_features(
            recognizer, store, s, model_sha256, ()
        )
        held_out_pairs.append((plain_f, lbl))
        held_chars += len(lbl)

    if len(held_out_pairs) < MIN_HELDOUT_SAMPLES or held_chars < MIN_HELDOUT_CHARS:
        return _store_inactive(
            "insufficient_evidence",
            (
                f"קובץ ה-.npz נשמר כגרסה לא-פעילה עבור {profile.name}: "
                "קבוצת הבקרה העצמאית עדיין קטנה מדי להוכחת שיפור מהימנה."
            ),
            train_samples=len(train_samples),
            held_out_samples=len(held_out_pairs),
            held_out_chars=held_chars,
        )

    charset = getattr(recognizer, "charset", None)
    prev_held = evaluate_head_detailed(W_prev, b_prev, held_out_pairs, charset)
    base_held = evaluate_head_detailed(W0, b0, held_out_pairs, charset)
    cand_held = evaluate_head_detailed(W_imp, b_imp, held_out_pairs, charset)

    held_cer_before = float(prev_held["cer"])
    held_wer_before = float(prev_held["wer"])
    held_cer_after = float(cand_held["cer"])
    held_wer_after = float(cand_held["wer"])
    ref_cer = min(held_cer_before, float(base_held["cer"]))
    ref_nll = min(float(prev_held["nll"]), float(base_held["nll"]))

    cer_improved = held_cer_after < (ref_cer - 1e-6)
    tied_better_calibrated = (
        abs(held_cer_after - ref_cer) <= 1e-6
        and held_cer_after < (float(base_held["cer"]) - 1e-6)
        and float(cand_held["nll"]) < (ref_nll - 0.02)
        and held_wer_after <= (held_wer_before + 1e-6)
    )
    if not (cer_improved or tied_better_calibrated):
        return _store_inactive(
            "kept_previous",
            (
                f"המתאם המיובא נשמר כגרסה לא-פעילה משום שלא שיפר את הדיוק על שורות הבקרה "
                f"({held_cer_before * 100:.1f}% לפני לעומת {held_cer_after * 100:.1f}% במתאם המיובא) — "
                "המודל הפעיל נשמר ללא שינוי."
            ),
            train_samples=len(train_samples),
            held_out_samples=len(held_out_pairs),
            held_out_chars=held_chars,
            held_out_cer_before=held_cer_before,
            held_out_cer_after=held_cer_after,
            held_out_wer_before=held_wer_before,
            held_out_wer_after=held_wer_after,
        )

    existing_rounds = [
        v.round_number for v in store.list_adapter_versions(profile.writer_id)
    ]
    new_round = max([int(profile.active_round), *existing_rounds], default=0) + 1
    rel_head = f"writers/{profile.writer_id}/heads/head-r{new_round:04d}.npz"
    round_path = store.root.joinpath(*rel_head.split("/"))
    round_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, round_path)
    shutil.copy2(src, store.writer_head_path(profile.writer_id))

    meta = {
        "writer_id": profile.writer_id,
        "writer_name": profile.name,
        "round": new_round,
        "source": "external_online_import",
        "model_sha256": model_sha256,
        "samples_total": len(samples),
        "train_samples": len(train_samples),
        "held_out_samples": len(held_out_pairs),
        "held_out_chars": held_chars,
        "held_out_cer_before": round(held_cer_before, 4),
        "held_out_cer_after": round(held_cer_after, 4),
        "held_out_wer_before": round(held_wer_before, 4),
        "held_out_wer_after": round(held_wer_after, 4),
    }
    store.writer_head_meta_path(profile.writer_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    store.record_adapter_version(
        profile.writer_id,
        round_number=new_round,
        head_relpath=rel_head,
        model_sha256=model_sha256,
        samples_total=len(samples),
        train_samples=len(train_samples),
        held_out_samples=len(held_out_pairs),
        held_out_chars=held_chars,
        held_out_cer_before=meta["held_out_cer_before"],
        held_out_cer_after=meta["held_out_cer_after"],
        held_out_wer_before=meta["held_out_wer_before"],
        held_out_wer_after=meta["held_out_wer_after"],
        activate=True,
    )
    return AdaptationReport(
        writer_id=profile.writer_id,
        writer_name=profile.name,
        accepted=True,
        status="accepted",
        active_round=new_round,
        samples_total=len(samples),
        train_samples=len(train_samples),
        held_out_samples=len(held_out_pairs),
        held_out_chars=held_chars,
        held_out_cer_before=held_cer_before,
        held_out_cer_after=held_cer_after,
        held_out_wer_before=held_wer_before,
        held_out_wer_after=held_wer_after,
        train_cer_before=0.0,
        train_cer_after=0.0,
        message=(
            f"המתאם החיצוני הוכיח שיפור על קבוצת הבקרה של {profile.name} "
            f"({held_cer_before * 100:.1f}% → {held_cer_after * 100:.1f}% CER) "
            f"והופעל כגרסה #{new_round}."
        ),
    )


def import_external_adapter_npz(
    writer_id: str,
    npz_path: str | Path,
    *,
    store_root: str | Path | None = None,
    model_path: str | Path | None = None,
    recognizer_factory=None,
    expected_vocab_size: int = 198,
    expected_feat_dim: int = 512,
    timeout_seconds: float = 300.0,
) -> AdaptationReport:
    """Safely validate, evaluate on held-out lines, and import an external ``.npz`` head."""
    import shutil
    from .mishkefet import mishkefet_importable
    from .models import MODEL_ARTIFACTS, models_directory
    from .worker import worker_path

    if recognizer_factory is None and not mishkefet_importable():
        src = Path(npz_path)
        _validate_npz_head_pure_python(
            src,
            expected_vocab_size=expected_vocab_size,
            expected_feat_dim=expected_feat_dim,
        )
        store = SchoolLearningStore(store_root)
        profile = store.get_writer(writer_id)
        if profile is None:
            raise KeyError(f"לא נמצא פרופיל תלמיד עבור {writer_id!r}.")
        art = MODEL_ARTIFACTS.get("mishkefet-v1")
        m_path = (
            Path(model_path)
            if model_path is not None
            else models_directory() / (art.filename if art else "mishkefet-v1.pt")
        )
        w_exe = worker_path()
        if (
            w_exe is not None
            and w_exe.is_file()
            and m_path.is_file()
            and len(store.list_writer_samples(profile.writer_id)) >= MIN_VERIFIED_FOR_ADAPT
        ):
            with tempfile.TemporaryDirectory(prefix="hw-imp-") as td:
                shutil.copyfile(src, Path(td) / "candidate.npz")
                job_file = Path(td) / "import-job.json"
                res_file = Path(td) / "import-result.json"
                job_file.write_text(
                    json.dumps(
                        {
                            "mode": "import_npz",
                            "writer_id": profile.writer_id,
                            "model_path": str(m_path),
                            "learning_dir": str(store.root),
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
                        f"ייבוא מתאם כתב היד נכשל ({proc.returncode}): {err}"
                    )
                payload = json.loads(res_file.read_text(encoding="utf-8"))
                if payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                return AdaptationReport.from_dict(payload)

    return import_external_adapter_in_process(
        writer_id,
        npz_path,
        store_root=store_root,
        model_path=model_path,
        recognizer_factory=recognizer_factory,
        expected_vocab_size=expected_vocab_size,
        expected_feat_dim=expected_feat_dim,
    )

