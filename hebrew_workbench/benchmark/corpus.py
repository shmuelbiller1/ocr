"""The corpora that the accuracy of the recognition is measured on.

A corpus is a folder with a file ``corpus.json`` in it:

```json
{
  "name": "Modern school handwriting",
  "description": "Pages written by students in class.",
  "target": "modern",
  "license": "the agreement of the school",
  "pages": [
    {
      "image": "pages/class7a_page01.jpg",
      "transcript": "transcripts/class7a_page01.txt",
      "writer": "student 7a-01",
      "date": "2026-03-12",
      "verified_by": ["teacher name"],
      "notes": "the abbreviations of the pupil were kept"
    }
  ]
}
```

The transcript of a page is a text file with one line of the page on
every line, in the order of the page, with the abbreviations and the
spelling of the writer kept as they are.  A file in the PAGE XML form
of the Pinkas dataset is read as well.

A page is only measured when its transcript was verified by somebody
who is not the one who wrote it down - a teacher of the class, for
example.  A corpus in which no page was verified is **not** a
measurement of the recognition, and the program says so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

__all__ = [
    "Corpus",
    "Page",
    "load_corpus",
    "read_transcript",
    "read_page_xml_report",
    "pinkas_pages",
    "UNREADABLE",
    "CORPUS_FILE",
]

CORPUS_FILE = "corpus.json"

#: The mark of a line of a transcript that could not be read.
UNREADABLE = "[?]"


@dataclass
class Page:
    """One page of a corpus, with its ground truth."""

    image: Path
    transcript: Path | None = None
    text: str = ""
    report: dict = field(default_factory=dict)
    writer: str = ""
    date: str = ""
    verified_by: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def complete(self) -> bool:
        """Is the ground truth of the page complete?

        A page whose transcript could not be read is not complete, and
        it is not measured: the engine would be blamed for a line that
        is not there.  A page that has no transcript at all is not
        complete either.
        """
        return bool(self.report.get("complete", False))

    @property
    def verified(self) -> bool:
        """Was the transcript checked by somebody else?"""
        return bool(self.verified_by)

    def digest(self) -> str:
        """The SHA-256 of the image of the page."""
        if not self.image.is_file():
            return ""
        return hashlib.sha256(self.image.read_bytes()).hexdigest()


@dataclass
class Corpus:
    """A set of pages that are measured together."""

    name: str = ""
    description: str = ""
    target: str = "modern"
    license: str = ""
    citation: str = ""
    url: str = ""
    folder: Path | None = None
    pages: list[Page] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        """Is every page of the corpus verified and complete?"""
        if not self.pages:
            return False
        return all(page.verified and page.complete for page in self.pages)

    @property
    def measured_pages(self) -> list[Page]:
        """The pages that can be measured: verified and complete."""
        return [
            page for page in self.pages if page.verified and page.complete
        ]

    def summary(self) -> dict:
        """What is known about the corpus, for the report."""
        return {
            "name": self.name,
            "description": self.description,
            "target": self.target,
            "license": self.license,
            "citation": self.citation,
            "url": self.url,
            "pages": len(self.pages),
            "pages_measured": len(self.measured_pages),
            "pages_without_verification": [
                page.image.name for page in self.pages if not page.verified
            ],
            "verified": self.verified,
        }


def _names(value) -> list[str]:
    """The names of the people who checked a transcript.

    One name may be given as a plain string, and several names may be
    given as a list.  A blank name is not a name at all, and it is left
    out.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    found = []
    for item in value:
        name = str(item).strip()
        if name:
            found.append(name)
    return found


def _tag(element) -> str:
    """The name of an element, without the namespace it may have."""
    return element.tag.rsplit("}", 1)[-1]


def _own_text(element) -> list[str]:
    """The texts that belong to the element itself."""
    found = []
    for child in element:
        tag = _tag(child)
        if tag == "Word":
            continue
        if tag == "Unicode":
            text = (child.text or "").strip()
            if text:
                found.append(text)
            continue
        found.extend(_own_text(child))
    return found


def _line_text(line) -> str:
    """The text of one line of a PAGE XML file."""
    own = _own_text(line)
    if own:
        return max(own, key=len)
    words = []
    for child in line:
        if _tag(child) != "Word":
            continue
        texts = _own_text(child)
        if texts:
            words.append(max(texts, key=len))
    return " ".join(words)


def _word_text(word) -> str:
    """The text of one word of a PAGE XML file."""
    texts = _own_text(word)
    return max(texts, key=len) if texts else ""


def read_page_xml_report(path: Path) -> tuple[str, dict]:
    """The ground truth of a page in the PAGE XML form, and what it holds.

    The report says how many lines and how many words the file holds,
    how many of them have a text, and how many lines were read from the
    words alone.  A file whose lines do not all have a text is not a
    full ground truth, and the measurement of such a page is not a
    measurement of the recognition.
    """
    tree = ElementTree.parse(path)
    lines = []
    report = {
        "lines": 0,
        "lines_with_text": 0,
        "lines_from_words": 0,
        "lines_incomplete": 0,
        "lines_unreadable": 0,
        "words": 0,
        "words_with_text": 0,
        "characters": 0,
    }
    for line in tree.iter():
        if _tag(line) != "TextLine":
            continue
        report["lines"] += 1
        words = [child for child in line if _tag(child) == "Word"]
        words_with_text = sum(1 for word in words if _word_text(word))
        report["words"] += len(words)
        report["words_with_text"] += words_with_text
        own = _own_text(line)
        text = _line_text(line)
        if not own and words:
            report["lines_from_words"] += 1
            if words_with_text != len(words):
                # The line has no text of its own, and only some of its
                # words have one: the line is not fully transcribed.
                report["lines_incomplete"] += 1
        if not text:
            report["lines_incomplete"] += 1
            continue
        if UNREADABLE in text:
            # A line that could not be read is marked `[?]` in this
            # form as well, and the rule of the plain text form is the
            # same: the line is missing from the ground truth, and the
            # page is not measured.
            report["lines_incomplete"] += 1
            report["lines_unreadable"] += 1
        lines.append(text)
        report["lines_with_text"] += 1
        report["characters"] += len(text)
    report["complete"] = report["lines_incomplete"] == 0
    return "\n".join(lines), report


def read_transcript(path: Path) -> tuple[str, dict]:
    """The ground truth of a page, and what the file really holds.

    Two forms are read: a text file with one line of the page on every
    line, and a PAGE XML file.
    """
    if path.suffix.lower() == ".xml":
        return read_page_xml_report(path)
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    # A line that could not be read is marked `[?]` in the transcript.
    # Such a line is missing from the ground truth, and a page with one
    # is not measured: the engine would be blamed for a line that is
    # not there.
    unreadable = sum(1 for line in lines if UNREADABLE in line)
    report = {
        "lines": len(lines),
        "lines_with_text": len(lines),
        "lines_from_words": 0,
        "lines_incomplete": unreadable,
        "lines_unreadable": unreadable,
        "words": sum(len(line.split()) for line in lines),
        "words_with_text": sum(len(line.split()) for line in lines),
        "characters": sum(len(line) for line in lines),
        "complete": bool(lines) and unreadable == 0,
    }
    return "\n".join(lines), report


def load_corpus(folder: Path) -> Corpus:
    """Read the corpus of a folder.

    A folder without a ``corpus.json`` is not a corpus, and the reason
    is returned in the errors of the corpus.
    """
    folder = Path(folder)
    corpus = Corpus(folder=folder)
    description = folder / CORPUS_FILE
    if not description.is_file():
        corpus.errors.append(f"the folder has no {CORPUS_FILE} in it")
        return corpus
    try:
        data = json.loads(description.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        corpus.errors.append(f"the {CORPUS_FILE} could not be read: {exc}")
        return corpus
    if not isinstance(data, dict):
        corpus.errors.append(f"the {CORPUS_FILE} has to be an object")
        return corpus

    corpus.name = str(data.get("name", ""))
    corpus.description = str(data.get("description", ""))
    corpus.target = str(data.get("target", "modern"))
    corpus.license = str(data.get("license", ""))
    corpus.citation = str(data.get("citation", ""))
    corpus.url = str(data.get("url", ""))

    pages = data.get("pages", [])
    if not isinstance(pages, list):
        corpus.errors.append("the pages of the corpus have to be a list")
        return corpus

    for entry in pages:
        if not isinstance(entry, dict):
            corpus.errors.append("a page of the corpus is not an object")
            continue
        image_name = str(entry.get("image", "")).strip()
        if not image_name:
            corpus.errors.append("a page of the corpus has no image")
            continue
        image = folder / image_name
        transcript_name = str(entry.get("transcript", "")).strip()
        transcript = folder / transcript_name if transcript_name else None
        page = Page(
            image=image,
            transcript=transcript,
            writer=str(entry.get("writer", "")),
            date=str(entry.get("date", "")),
            verified_by=_names(entry.get("verified_by")),
            notes=str(entry.get("notes", "")),
        )
        if not image.is_file():
            corpus.errors.append(f"the image of the page is missing: {image_name}")
            corpus.pages.append(page)
            continue
        if transcript is None or not transcript.is_file():
            corpus.errors.append(
                f"the transcript of the page is missing: {image_name}"
            )
            corpus.pages.append(page)
            continue
        try:
            text, report = read_transcript(transcript)
        except (OSError, ValueError, ElementTree.ParseError) as exc:
            corpus.errors.append(
                f"the transcript of the page could not be read: {image_name} ({exc})"
            )
            corpus.pages.append(page)
            continue
        page.text = text
        page.report = report
        corpus.pages.append(page)
    return corpus


def pinkas_pages(root: Path) -> list[Page]:
    """The pages of the Pinkas dataset, with their ground truth.

    The dataset is the *diagnostic* corpus: pages of early modern
    (1500-1800) records.  It is not the material the program is meant
    for, and it is not used to decide which engine is the better one.
    """
    root = Path(root)
    pages = []
    for xml_path in sorted(root.rglob("*.xml")):
        page_image = xml_path.with_suffix(".jpg")
        if not page_image.exists():
            page_image = xml_path.with_suffix(".png")
        if not page_image.exists():
            continue
        page = Page(
            image=page_image,
            transcript=xml_path,
            # The ground truth of the dataset was made and checked by
            # the authors of the dataset, and published with it.
            verified_by=["The Pinkas Dataset (ICDAR 2019)"],
        )
        try:
            text, report = read_page_xml_report(xml_path)
        except (OSError, ElementTree.ParseError):
            continue
        page.text = text
        page.report = report
        pages.append(page)
    return pages
