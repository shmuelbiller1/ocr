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
import time
from pathlib import Path

BRANCH = "ci/diagnostics"
FOLDER = "ci-diagnostics"


def run(command: list[str]) -> int:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
    return result.returncode


def push_with_retry(branch: str, attempts: int = 4) -> int:
    """Push the diagnostics, and try again when the push was refused.

    Several jobs of the same build publish to the same branch, and one
    of them may push between the moment this job made its commit and
    the moment it pushes.  The push is then refused, and the build
    would fail for a reason that has nothing to do with the program.
    """
    for attempt in range(1, attempts + 1):
        code = run(
            ["git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}"]
        )
        if code == 0:
            return 0
        if attempt < attempts:
            print(
                f"the push to {branch} was refused, trying again "
                f"({attempt} of {attempts})",
                file=sys.stderr,
            )
            time.sleep(3 * attempt)
    return 1


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
    if run(["git", "add", "-f", FOLDER]) != 0:
        sys.stderr.write("the diagnostics could not be added to the index\n")
        return 1
    if (
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
        != 0
    ):
        sys.stderr.write("the diagnostics could not be committed\n")
        return 1
    if push_with_retry(branch) != 0:
        return 1
    print(f"published {copied} to {branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
