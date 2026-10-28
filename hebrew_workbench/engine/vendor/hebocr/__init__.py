"""The recognition code of Mishkefet-v1, as it was published.

Source: https://github.com/itayinbarr/heb-ocr (MIT, Copyright (c) 2026
Itay Inbar).  The files were copied as they were published; the licence
text is in ``docs/licences/HEB-OCR-MIT.txt``.

Only the parts that recognise a page are here.  The parts that build a
training set, that fine-tune a model and that build a language model are
not, because the program never trains anything and never rewrites the text
of a recognition with a language model.
"""
