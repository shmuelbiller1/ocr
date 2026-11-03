"""The recognition worker.

This is the small executable that carries the machine learning library.
The main application starts it, hands it a document and a model file, and
reads the transcription back.  Keeping it separate means the main
application stays small and that a crash in the engine cannot take the
user interface with it.

The worker is built by the packaging job::

    pyinstaller --onefile --console --name ocr-worker ocr_worker/main.py
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# Make the package importable when the worker runs from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _engine_of(job: dict):
    """The engine that the job asks for.

    The worker can run more than one engine.  The job says which one,
    and an unknown name is an error and not a silent fall back to the
    first engine that happens to be there.
    """
    name = str(job.get("engine") or "kraken")
    model_path = job["model_path"]
    page_enh = (
        bool(job["page_enhancement"])
        if "page_enhancement" in job and job["page_enhancement"] is not None
        else None
    )
    if name == "mishkefet":
        from hebrew_workbench.engine.mishkefet import MishkefetEngine

        return MishkefetEngine(
            model_path,
            artifact_id="mishkefet-v1",
            mode=job.get("decoding_mode", "raw"),
            page_enhancement=page_enh,
        )
    if name == "kraken":
        from hebrew_workbench.engine.kraken_local import KrakenEngine

        return KrakenEngine(model_path, page_enhancement=page_enh)
    raise ValueError(f"unknown engine: {name}")


def _install_offline_guard(attempts: list) -> None:
    """Deny non-loopback Python socket access during packaged offline checks.

    Local IPC is allowed. This is not an OS firewall for native libraries.
    Every denied attempt is reported even if a dependency catches the error.
    """
    import ipaddress

    def guard(event, args):
        host = None
        if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
            host = args[0]
        elif event == "socket.getnameinfo":
            host = args[0][0]
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            address = args[-1]
            if isinstance(address, tuple):
                host = address[0]
        if host is None or host in ("localhost", "127.0.0.1", "::1"):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        attempts.append({"event": event, "host": str(host)})
        raise OSError("Offline check: outbound network access is forbidden")

    sys.addaudithook(guard)


def _run_enhance_preview(input_path: Path, output_path: Path, enabled: bool) -> int:
    """Render processed-page preview PNG via worker vision libs for GUI comparison."""
    from PIL import Image
    from hebrew_workbench.engine.photocraft_audit import (
        encode_preview_png,
        prepare_page_for_ocr,
        resolve_page_enhancement_enabled,
    )

    eff = resolve_page_enhancement_enabled(enabled)
    with Image.open(input_path) as im:
        prepared, audit = prepare_page_for_ocr(im, enabled=eff)
        was_enhanced = bool(eff and audit is not None and audit.needs_adjustment)
        png = encode_preview_png(prepared) or b""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png)
    meta_path = output_path.with_suffix(".json")
    meta_path.write_text(
        json.dumps(
            {
                "enhanced": was_enhanced,
                "enhancement_enabled": eff,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hebrew Notes Workbench OCR worker")
    parser.add_argument("--job", help="path of the job description")
    parser.add_argument("--result", help="path of the result file")
    parser.add_argument("--enhance-preview", help="input image for processed preview")
    parser.add_argument("--output-preview", help="output PNG for processed preview")
    parser.add_argument(
        "--disable-enhancement",
        action="store_true",
        help="run preview with automatic page enhancement disabled",
    )
    args = parser.parse_args(argv)

    if args.enhance_preview and args.output_preview:
        return _run_enhance_preview(
            Path(args.enhance_preview),
            Path(args.output_preview),
            enabled=not args.disable_enhancement,
        )
    if not args.job or not args.result:
        parser.error("--job and --result are required unless --enhance-preview is used")

    job_path = Path(args.job)
    result_path = Path(args.result)

    attempts = []
    offline_check = False
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        offline_check = job.get("offline_check") is True
        if offline_check:
            _install_offline_guard(attempts)
        engine = _engine_of(job)
        result = engine.recognize(job["document"])
        pages_payload = []
        for page in result.pages:
            proc_name = None
            if getattr(page, "processed_image_png", None):
                proc_name = f"processed-page-{page.number}.png"
                try:
                    (result_path.parent / proc_name).write_bytes(
                        page.processed_image_png
                    )
                except OSError:
                    proc_name = None
            pages_payload.append(
                {
                    "number": page.number,
                    "text": page.text,
                    "confidence": page.confidence,
                    "assisted_text": page.assisted_text,
                    "enhanced": bool(getattr(page, "enhanced", False)),
                    "enhancement_enabled": bool(
                        getattr(page, "enhancement_enabled", True)
                    ),
                    "processed_image_file": proc_name,
                    "lines": [
                        {
                            "text": line.text,
                            "confidence": line.confidence,
                            "box": list(line.box) if line.box else None,
                        }
                        for line in page.lines
                    ],
                }
            )
        payload = {
            "text": result.text,
            "engine_name": result.engine_name,
            "duration_seconds": result.duration_seconds,
            "assisted_text": result.assisted_text,
            "decoding_mode": result.decoding_mode,
            "pages": pages_payload,
        }
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        # The message also goes to the error output, so that it is not
        # lost when the result file cannot be read.
        print(message, file=sys.stderr)
        payload = {"error": message, "traceback": traceback.format_exc()}

    if offline_check:
        payload["offline_check"] = {"enabled": True, "blocked_attempts": attempts}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if "error" not in payload else 1


if __name__ == "__main__":
    raise SystemExit(main())
