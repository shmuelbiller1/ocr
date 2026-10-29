# Packaging audit: remove dead collection, not offline capabilities

## Scope

This is a conservative packaging change, not a new OCR runtime. No model,
engine, supported image codec, PDF renderer, editing/export/printing feature,
licence notice or source test is deleted. No third-party source is patched,
and no placeholder module is inserted to hide missing dependencies.

The separate one-click/offline installer work (PR #15) is not modified here.
This branch's regular ZIP still expects separately installed recognition
weights (and optional assisted-decoding files). Preparing those local assets
is a prerequisite for offline OCR; a smaller ZIP does not itself provide them.
Mishkefet's non-commercial assets must not silently be redistributed in the
regular release. Already downloaded files are never removed by this change.

## What is actually dead, and what only looks dead

Audit based on the pinned `kraken==7.1.1` wheel and the app's actual imports.

| Component | Decision | Evidence / reason |
| --- | --- | --- |
| `kraken.ketos` | Exclude from frozen worker | Training/dataset command-line commands; app invokes `kraken.tasks`, not these CLI entry points. |
| `kraken.kraken` | Exclude from frozen worker | Kraken's separate CLI; the worker has its own entry point. |
| `kraken.contrib` | Exclude from frozen worker | Contribution/developer scripts; not imported by our recognition path. |
| OpenCV `opencv_videoio_ffmpeg*.dll` | Remove only this separately loaded video plugin | The app reads still images/PDFs; segmentation uses OpenCV image operations, never VideoCapture/VideoWriter. `cv2.pyd` and image codecs stay. |
| Blanket `--collect-all kraken` | Replace in inference profile | Prefer normal dependency analysis, explicit dynamically resolved model modules, metadata and required resources. A baseline profile retains the old recipe for comparison. |
| **PyArrow** | **Keep** | `kraken.models.ctc` and `kraken.lib.vgsl.spred` import `ImageInputTransforms` from `kraken.lib.dataset`; its `__init__` imports `recognition`, which imports `pyarrow` and `pyarrow.compute` at module scope. Not safely dead without changing upstream library boundaries. |
| **Lightning** | **Keep** | Both `kraken.lib.ppocr.model` and `kraken.lib.vgsl.model` import `lightning.fabric.Fabric` in the inference path. |
| **torchvision** | **Keep full `--collect-all`** | Used by Kraken transforms; its initializer needs native operators too. Actual Windows testing proved that the PyInstaller 6.16 hook looks for old `_C`/`image` names, missing the pinned wheel’s `_C_stable.pyd` / `image_stable.pyd`. The narrower candidate failed with `operator torchvision::nms does not exist`. Restore full collection rather than pretending these files are dead. |
| **SciPy / scikit-image / scikit-learn** | **Keep for this pass** | Segmentation and transitive inference imports are intertwined; size alone does not establish dead code. |
| **PyTorch / OpenCV / NumPy / PDFium / Qt** | **Keep** | Required for current engines, segmentation, PDF handling and UI. |
| **AVIF / other image codecs** | **Keep** | No image codec trimming in this pass. |
| Tests/docs in repository | Keep | Not a useful target for runtime slimming; tests are required to validate exclusions. |

The frozen inference build preserves `kraken` distribution metadata, needed
by `importlib.metadata.entry_points` for model loaders/classes. It explicitly
collects all four registered model modules (`kraken.lib.ppocr`, `kraken.lib.vgsl`,
`kraken.lib.ro`, `kraken.lib.pretrain`), and the local
`blla.mlmodel`, `iso15924.json` and dataset `scripts.json` resources. Removing
`blla.mlmodel` would break offline segmentation even with recognition weights
already present. A missing required resource fails the build.

## Reproducible evidence, not estimated savings

Both worker builds now use `tools/build_worker.py`:

- `--profile baseline`: previous collect-all build, unchanged.
- `--profile inference`: targeted collection and the exact video-plugin deletion.
- Build reports record profile, explicit exclusions/deletions and actual bytes.
- A Kraken version change requires re-auditing rather than silently reusing the
  version-specific policy.

The worker CI job builds **both profiles on the same Windows runner**, with
identical dependency pins. `tools/verify_worker_bundle.py` records actual
uncompressed bytes by component and equally compressed worker-only ZIP sizes.
These are not whole-app download-size savings. Cold subprocess wall time
includes imports and model loading; it is not pure OCR latency. Memory is not
measured, and no memory saving is claimed.

## Offline and output-equivalence gate

Both baseline and inference workers must read the same local files:

1. Kraken small on the supplied PDF.
2. Kraken medium on the same PDF.
3. Mishkefet raw on an image.
4. Mishkefet beam + three scales on the PDF.
5. Mishkefet assisted on the PDF, with both local language-model files.

Every run uses an empty working directory outside the checkout, no source
PYTHONPATH, isolated user/cache directories and offline environment flags.
A worker audit hook denies non-loopback **Python socket** access. Even a
caught/ignored denied attempt fails verification. Local IPC remains allowed.
This is not an OS firewall and does not instrument arbitrary native DLL
network calls; the report states this limitation explicitly.

Any missing resource, failed model, empty reading, silent profile fallback,
network attempt, or difference in raw/alternative text fails the comparison.
The inference bundle must also be measurably smaller. No recognised words,
abbreviations, line order or points may be changed to make the test pass.

The actual release ZIP is additionally unpacked and launched, and its own
worker runs all five offline checks. Existing full GUI tests retain preview,
settings, project saving, export and print coverage. Model downloads happen
only in CI setup, before these offline checks—not during inference.

Until these packaged Windows checks pass, the policy is a **candidate**, not
a verified safe removal or a promised size saving. Results are published in
`worker-packaging-audit` / `package-comparison.json` and release diagnostics.
