"""Self-test support.

The Windows build is only considered good if the packaged executable
actually starts.  ``hebrew_workbench.selftest`` runs a small number of
staged checks inside the real application and writes a JSON report, so
the CI job can fail loudly instead of assuming that a produced ``.exe``
file means a working application.

The self-test is written to survive a broken installation: every stage is
guarded, the report file is written even when a stage crashes, and the
process always ends with a meaningful exit code.
"""

from __future__ import annotations

import json
import platform
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["CheckResult", "run_checks", "main"]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class _Report:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name=name, ok=ok, detail=detail))

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)


def _write_line(text: str) -> None:
    """Print without ever raising (a windowed build has no console)."""
    try:
        print(text)
    except Exception:
        pass


def _check_imports(report: _Report) -> None:
    modules = [
        "hebrew_workbench",
        "hebrew_workbench.engine.base",
        "hebrew_workbench.engine.registry",
        "hebrew_workbench.project",
    ]
    failures = []
    for name in modules:
        try:
            __import__(name)
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"{name}: {exc}")
    report.add(
        "core-imports",
        not failures,
        "; ".join(failures) if failures else "all core modules import cleanly",
    )


def _check_engine_contract(report: _Report) -> None:
    from .engine.base import EngineUnavailable, OCRResult
    from .engine.registry import EngineRegistry

    problems = []
    registry = EngineRegistry()
    if registry.engine.available():
        problems.append("the default engine must not report itself as available")
    try:
        registry.transcribe(Path("does-not-exist.png"))
    except FileNotFoundError:
        pass
    except Exception as exc:
        problems.append(f"missing files must raise FileNotFoundError, got {exc!r}")
    try:
        registry.transcribe(__file__)
    except EngineUnavailable:
        pass
    except Exception as exc:
        problems.append(f"an unavailable engine must raise EngineUnavailable, got {exc!r}")
    else:
        problems.append("an unavailable engine must raise EngineUnavailable")

    class _Fake:
        name = "self-test adapter"

        def available(self) -> bool:
            return True

        def recognize(self, file_path: Path) -> OCRResult:
            return OCRResult("שלום", self.name)

    try:
        result = EngineRegistry(_Fake()).transcribe(__file__)
    except Exception as exc:
        problems.append(f"a working adapter must produce a result, got {exc!r}")
    else:
        if result.text != "שלום" or result.engine_name != "self-test adapter":
            problems.append("a working adapter must return its own result untouched")
    report.add(
        "engine-contract",
        not problems,
        "; ".join(problems) if problems else "the engine contract fails closed",
    )


def _check_gui(report: _Report) -> None:
    try:
        from PySide6.QtWidgets import QApplication

        from .ui.main_window import MainWindow
    except Exception as exc:  # pragma: no cover - defensive
        report.add(
            "gui-startup",
            False,
            f"the user interface could not be imported: {exc}\n{traceback.format_exc()}",
        )
        return

    app = QApplication.instance() or QApplication([])
    try:
        window = MainWindow()
        window.show()
        app.processEvents()
        visible = window.isVisible()
        title = window.windowTitle()
        window.close()
        app.processEvents()
    except Exception as exc:  # pragma: no cover - defensive
        report.add(
            "gui-startup",
            False,
            f"the main window could not be created: {exc}\n{traceback.format_exc()}",
        )
        return
    report.add(
        "gui-startup",
        bool(visible) and bool(title),
        f"main window created with title {title!r}",
    )


def run_checks() -> list[CheckResult]:
    """Run every staged check and return the individual results."""
    report = _Report()
    report.add(
        "environment",
        True,
        f"python {platform.python_version()} on {platform.platform()}",
    )
    for name, check in (
        ("core-imports", _check_imports),
        ("engine-contract", _check_engine_contract),
        ("gui-startup", _check_gui),
    ):
        try:
            check(report)
        except Exception as exc:  # pragma: no cover - defensive
            report.add(name, False, f"the check crashed: {exc!r}")
    return report.results


def _write_report(path: str | Path, payload: dict) -> bool:
    try:
        target = Path(path)
        if target.parent and str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def main(report_path: str | Path | None = None) -> int:
    """Run the self-test and optionally write a JSON report.

    Returns the process exit code: ``0`` when every check passed.
    """
    results: list[CheckResult] = []
    crash = ""
    try:
        results = run_checks()
    except Exception as exc:  # pragma: no cover - defensive
        crash = f"{exc!r}\n{traceback.format_exc()}"
        results = [CheckResult("selftest", False, f"the self-test crashed: {crash}")]

    payload = {
        "ok": all(result.ok for result in results) and not crash,
        "python": sys.version,
        "results": [result.to_dict() for result in results],
    }
    if crash:
        payload["crash"] = crash

    if report_path:
        _write_report(report_path, payload)

    _write_line(json.dumps(payload, ensure_ascii=False, indent=2))
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        _write_line(f"[{status}] {result.name}: {result.detail}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
