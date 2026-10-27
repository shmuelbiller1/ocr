"""Self-test support.

The Windows build is only considered good if the packaged executable
actually starts.  ``hebrew_workbench.selftest`` runs a small number of
staged checks inside the real application and writes a JSON report, so
the CI job can fail loudly instead of assuming that a produced ``.exe``
file means a working application.
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
        report.add("gui-startup", False, f"the user interface could not be imported: {exc}")
        return

    app = QApplication.instance() or QApplication([])
    try:
        window = MainWindow()
        window.show()
        app.processEvents()
        visible = window.isVisible()
        title = window.windowTitle()
        window.close()
    except Exception as exc:  # pragma: no cover - defensive
        report.add("gui-startup", False, f"the main window could not be created: {exc}")
        return
    finally:
        app.processEvents()
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
    _check_imports(report)
    _check_engine_contract(report)
    _check_gui(report)
    return report.results


def main(report_path: str | Path | None = None) -> int:
    """Run the self-test and optionally write a JSON report.

    Returns the process exit code: ``0`` when every check passed.
    """
    results = run_checks()
    payload = {
        "ok": all(result.ok for result in results),
        "python": sys.version,
        "results": [result.to_dict() for result in results],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if report_path:
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    try:
        print(text)
    except Exception:  # pragma: no cover - a windowed build has no stdout
        pass
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        try:
            print(f"[{status}] {result.name}: {result.detail}", file=sys.stderr)
        except Exception:  # pragma: no cover
            pass
    return 0 if payload["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
