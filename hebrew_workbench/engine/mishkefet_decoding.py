"""Explicit, optional decoding profiles; no downloads or fallback at inference."""
from __future__ import annotations

import hashlib
import io
import pickle
from collections import Counter, defaultdict
from pathlib import Path

from .base import EngineFailure
from .models import ModelArtifact

MODES = ("raw", "beam", "assisted")
REVISION = "16380452d62839f369c36f17312c94d5d1af1768"
BASE_URL = f"https://huggingface.co/itayinbar/Mishkefet-v1/resolve/{REVISION}"
# Published LFS SHA-256/size, checked 2026-10-29. The model card applies
# CC-BY-NC-SA-4.0 to these files as well as the recognition checkpoint.
DECODING_ARTIFACTS = {
    key: ModelArtifact(
        id=key, name=name, filename=filename, url=f"{BASE_URL}/{filename}",
        size_bytes=size, sha256=digest, license="CC-BY-NC-SA-4.0",
        license_url=f"https://huggingface.co/itayinbar/Mishkefet-v1/blob/{REVISION}/README.md",
        script="Hebrew", engine="mishkefet", engine_version="Mishkefet-v1",
        notes="Optional language prior; non-commercial. Can change unusual words. Not bundled.",
    )
    for key, name, filename, size, digest in (
        ("mishkefet-char-lm", "Mishkefet character 6-gram LM", "hebrew_char6.pkl", 28241531,
         "60e6b974e797c74e2c543b27bfe1f9b02e8e8960594cfde7dc452553e4be2161"),
        ("mishkefet-word-lm", "Mishkefet word prior", "hebrew_words.pkl", 3796006,
         "39f8ed30114125d53a47d4c383e48338bd5f8ffce21ae981e5fd7f99ade08874"),
    )
}


def decoding_mode(options: dict) -> str:
    mode = options.get("decoding_mode", "raw")
    if mode not in MODES:
        raise ValueError(f"Unknown Mishkefet decoding mode: {mode!r}")
    return mode


class _DataOnlyUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError("Executable pickle globals are forbidden")


def _load_data(folder: Path, identifier: str) -> dict:
    artifact = DECODING_ARTIFACTS[identifier]
    path = folder / artifact.filename
    try:
        with path.open("rb") as stream:
            data = stream.read(artifact.size_bytes + 1)
    except OSError as exc:
        raise EngineFailure("Install the optional Mishkefet language models in Settings first.") from exc
    # Verify the very bytes deserialized, not a path that can be swapped.
    if len(data) != artifact.size_bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise EngineFailure(f"Language model failed integrity verification: {artifact.filename}")
    result = _DataOnlyUnpickler(io.BytesIO(data)).load()
    if not isinstance(result, dict):
        raise EngineFailure("Invalid language model data")
    return result


def load_language_models(folder: Path):
    from .vendor.hebocr.lm import CharNGramLM
    from .vendor.hebocr.wordlm import WordUnigramLM

    char_data = _load_data(folder, "mishkefet-char-lm")
    word_data = _load_data(folder, "mishkefet-word-lm")
    char_lm = CharNGramLM(order=char_data["order"], backoff=char_data["backoff"])
    char_lm.total = char_data["total"]
    char_lm.counts = [defaultdict(int, c) for c in char_data["counts"]]
    word_lm = WordUnigramLM(oov_logprob=word_data["oov_logprob"],
                           prefix_discount=word_data["prefix_discount"])
    word_lm.counts = Counter(word_data["counts"])
    word_lm.total = word_data["total"]
    return char_lm, word_lm
