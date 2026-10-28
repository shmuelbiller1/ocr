"""Download and verify a recognition model.

    python tools/download_model.py --model kraken-ppocrv6-small

The file is checked against the digest published by the model authors and
against the SHA-256 digest that this project pinned.  A file that does
not match is deleted and never used.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hebrew_workbench.console import use_utf8  # noqa: E402
from hebrew_workbench.engine.models import (  # noqa: E402
    MODEL_ARTIFACTS,
    InstallError,
    install_artifact,
    models_directory,
    sha256_of,
    verify_file,
)


def main(argv: list[str] | None = None) -> int:
    # The console of Windows cannot write Hebrew in the code page
    # of the system, and the program would stop in the middle of a
    # report because of a letter.
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default="kraken-ppocrv6-small",
        choices=sorted(MODEL_ARTIFACTS),
        help="which model to download",
    )
    parser.add_argument("--target", help="where to put the file")
    parser.add_argument(
        "--print-digest",
        action="store_true",
        help="print the SHA-256 digest of the downloaded file",
    )
    args = parser.parse_args(argv)

    artifact = MODEL_ARTIFACTS[args.model]
    target = Path(args.target) if args.target else models_directory()
    print(artifact.summary())
    try:
        path = install_artifact(artifact, target)
    except InstallError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    digest = sha256_of(path)
    print(f"downloaded: {path}")
    print(f"size: {path.stat().st_size} bytes")
    print(f"sha256: {digest}")
    if args.print_digest:
        print(json.dumps({"model": artifact.id, "sha256": digest, "size": path.stat().st_size}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
