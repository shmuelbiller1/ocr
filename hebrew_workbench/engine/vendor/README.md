# Third-party code in this folder

| Folder | Project | Licence | What it is used for |
| --- | --- | --- | --- |
| `hebocr/` | [itayinbarr/heb-ocr](https://github.com/itayinbarr/heb-ocr) | MIT (Copyright (c) 2026 Itay Inbar) — the text is in `docs/licences/HEB-OCR-MIT.txt` | the line recognition and the page segmentation of the engine *Mishkefet-v1* |

The files were copied as they were published and were not changed.  The
weights of the model are **not** here: they are downloaded by the user, on
request, and are checked against a digest (see `hebrew_workbench/engine/models.py`).
