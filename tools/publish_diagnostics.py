"""Publish the diagnostics of a build to the `ci/diagnostics` branch.

The log of a build is not reachable from every environment, so the build
copies the interesting parts - the exit code of the packaged executable,
its output, the self-test report - into a small text file and pushes it
to a branch that can be read with plain git.

    python tools/publish_diagnostics.py selftest-windows.json selftest-out.txt
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BRANCH = "ci/diagnostics"
FOLDER = "ci-diagnostics"


def run(command: list[str]) -> int:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    branch = BRANCH
    if argv and argv[0].startswith("--branch="):
        branch = argv.pop(0).split("=", 1)[1]
    if not argv:
        print("nothing to publish")
        return 0

    target = Path(FOLDER)
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in argv:
        source = Path(name)
        if not source.exists():
            continue
        destination = target / source.name
        try:
            destination.write_text(
                source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
            )
            copied.append(source.name)
        except OSError:
            continue

    if not copied:
        print("no diagnostics were found")
        return 0

    if run(["git", "checkout", "-B", branch]) != 0:
        return 1
    run(["git", "add", "-f", FOLDER])
    run(
        [
            "git",
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit",
            "-m",
            "ci: diagnostics of this build",
            "--allow-empty",
        ]
    )
    if run(["git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}"]) != 0:
        return 1
    print(f"published {copied} to {branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
