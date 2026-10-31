"""Turn an uploaded file into plain text. Formats: PDF, TXT and Markdown."""

import io
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PyPdfError


class ParseError(Exception):
    """The file cannot be read as text. The message is safe to show to users."""


def extension(filename: str) -> str:
    return PurePath(filename).suffix.lower().lstrip(".")


def parse(filename: str, data: bytes, supported: list[str]) -> str:
    kind = extension(filename)
    if kind not in supported:
        raise ParseError(f"Unsupported file type. Supported types: {', '.join(supported)}.")
    text = _pdf(data) if kind == "pdf" else _plain(data)
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
