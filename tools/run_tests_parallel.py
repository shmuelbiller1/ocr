#!/usr/bin/env python3
"""Run ``tests/test_*.py`` modules in parallel across CPU worker processes.

Uses only the Python standard library so ``Unit tests (Linux)`` and
``Windows executable`` jobs need no extra dependencies beyond ``requirements.txt``.
Each test module runs in its own isolated Python process, preventing ``QApplication``
singleton or global-state interference across modules while utilizing multiple cores.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _discover_test_modules(tests_dir: Path, pattern: str = "test_*.py") -> list[str]:
    files = sorted(tests_dir.glob(pattern))
    return [f"tests.{p.stem}" for p in files if p.is_file()]


def _run_one_module(
    spec: tuple[str, str, int],
) -> tuple[str, int, float, str]:
    python_exe, module_name, timeout_sec = spec
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [python_exe, "-m", "unittest", "-v", module_name],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        elapsed = time.perf_counter() - t0
        return module_name, proc.returncode, elapsed, proc.stdout
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - t0
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        msg = f"{partial}\n[TIMEOUT] {module_name} exceeded {timeout_sec}s\n"
        return module_name, 124, elapsed, msg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="number of worker processes (0 = auto based on CPU cores, capped at 8)",
    )
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        help="glob pattern inside tests/ (default: test_*.py)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="per-module timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--verbose-all",
        action="store_true",
        help="print full unittest output for passing modules as well as failures",
    )
    args = parser.parse_args(argv)

    modules = _discover_test_modules(ROOT / "tests", args.pattern)
    if not modules:
        print("No test modules discovered.", file=sys.stderr)
        return 1

    cpu_count = os.cpu_count() or 2
    workers = args.workers if args.workers > 0 else max(1, min(8, cpu_count))
    workers = min(workers, len(modules))

    t_start = time.perf_counter()
    results: list[tuple[str, int, float, str]] = []
    specs = [(sys.executable, mod, args.timeout) for mod in modules]

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_run_one_module, s): s[1] for s in specs}
        for fut in concurrent.futures.as_completed(future_map):
            mod, rc, dt, out = fut.result()
            results.append((mod, rc, dt, out))
            status = "PASS" if rc == 0 else f"FAIL(rc={rc})"
            print(f"[{status}] {mod} ({dt:.2f}s)", flush=True)
            if args.verbose_all or rc != 0:
                print(out, flush=True)

    wall = time.perf_counter() - t_start
    results.sort(key=lambda r: r[0])
    failed = [r for r in results if r[1] != 0]
    total_cpu = sum(r[2] for r in results)
    print(
        f"\nParallel test summary: {len(results) - len(failed)}/{len(results)} modules passed "
        f"in {wall:.2f}s wall ({total_cpu:.2f}s cumulative, workers={workers}).",
        flush=True,
    )
    if failed:
        print("Failed modules:", ", ".join(r[0] for r in failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
