"""Turn a file into plain text. Formats: PDF, TXT, Markdown, DOCX and HTML."""

import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePath
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PyPdfError

# A .docx is a zip of XML; refuse archives that would unpack to something absurd.
MAX_DOCX_XML_BYTES = 50 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ParseError(Exception):
    """The file cannot be read as text. The message is safe to show to users."""


def extension(filename: str) -> str:
    return PurePath(filename).suffix.lower().lstrip(".")


def parse(filename: str, data: bytes, supported: list[str]) -> str:
    kind = extension(filename)
    if kind not in supported:
        raise ParseError(f"Unsupported file type. Supported types: {', '.join(supported)}.")
    if kind == "pdf":
        text = _pdf(data)
    elif kind == "docx":
        text = _docx(data)
    elif kind in ("html", "htm"):
        text = _html(_plain(data))
    else:
        text = _plain(data)
    text = text.replace("\x00", "").strip()
    if not text:
        raise ParseError("The file contains no text.")
    return text


def _plain(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("The file is not valid UTF-8 text.") from exc


def _pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except (PyPdfError, ValueError, KeyError, OSError) as exc:
        raise ParseError("The PDF could not be read.") from exc


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ParseError("The Word document is too large to read.")
            xml = archive.read(info)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ParseError("The Word document could not be read.") from exc
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:  # never expand entities from untrusted files
        raise ParseError("The Word document could not be read.")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ParseError("The Word document could not be read.") from exc
    paragraphs = []
    for paragraph in root.iter(f"{_W}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n\n".join(p for p in paragraphs if p.strip())


# Elements whose content is not page text, elements that separate paragraphs, and elements that
# only start a new line (list items, line breaks, table rows).
_SKIPPED = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCKS = {
    "p", "div", "table", "section", "article", "header", "footer", "nav", "aside", "main",
    "blockquote", "pre", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
}  # fmt: skip
_LINES = {"br", "li", "tr", "hr"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag in _SKIPPED:
            self.skip_depth += 1
        elif tag in _BLOCKS or tag in _LINES:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in _SKIPPED:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        elif not self.skip_depth:
            self.parts.append(data)


def _html(markup: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(markup)
    extractor.close()
    lines = [
        re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(extractor.parts).split("\n")
    ]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    title = " ".join(extractor.title.split())
    return f"{title}\n\n{body}" if title and body else title or body
