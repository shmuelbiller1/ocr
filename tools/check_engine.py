"""Check that torch and torchvision belong together.

The recognition needs torch and torchvision to be a matching pair.  When
they are not, torchvision cannot load its own part, the operation
``torchvision::nms`` does not exist, and the recognition dies with
``RuntimeError: operator torchvision::nms does not exist``.

The script says what is installed and whether the operations of
torchvision work, so that a build fails early and with a clear message.

    python tools/check_engine.py
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        import torch
        import torchvision
    except ImportError as exc:
        sys.stderr.write(f"the engine could not be imported: {exc!r}\n")
        return 1

    print(f"torch {torch.__version__}")
    print(f"torchvision {torchvision.__version__}")

    try:
        # The operation exists only when torchvision was able to load
        # its own part, and that needs a torch of the right version.
        torch.ops.torchvision.nms
    except Exception as exc:  # noqa: BLE001 - any failure is a failure
        sys.stderr.write(
            "torchvision cannot use its own operations, so the recognition "
            f"will not start: {exc!r}\n"
        )
        return 1

    print("the operations of torchvision work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
