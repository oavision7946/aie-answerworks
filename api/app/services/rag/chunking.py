"""Text splitting. Every method returns chunks of at most `size` characters.

- fixed:     a sliding window of `size` characters that advances by `size - overlap`
- recursive: split on paragraphs, then lines, sentences and words until pieces fit, then pack
- paragraph: one unit per blank-line separated paragraph, packed up to `size`
- sentence:  one unit per sentence, packed up to `size`

Packing joins consecutive units while they fit. The next chunk starts with the trailing units of
the previous one that total at most `overlap` characters (none when overlap is 0).
"""

import re

from app.core.settings import ChunkingConfig

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# Boundaries tried in order by the recursive splitter; punctuation stays with its sentence.
SEPARATORS = (PARAGRAPH_BREAK, re.compile(r"\n"), SENTENCE_END, re.compile(r"\s+"))


def split_text(text: str, config: ChunkingConfig) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if config.method == "fixed":
        return _fixed(text, config.size, config.overlap)
    units = _units(text, config.method)
    pieces = [piece for unit in units for piece in _fit(unit, config.size)]
    return _pack(pieces, config.size, config.overlap)


def _units(text: str, method: str) -> list[str]:
    if method == "paragraph":
        parts = PARAGRAPH_BREAK.split(text)
    elif method == "sentence":
        parts = SENTENCE_END.split(text)
    else:
        parts = [text]
    return [part.strip() for part in parts if part.strip()]


def _fixed(text: str, size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while True:
        chunk = text[start : start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            return chunks
        start += size - overlap


def _fit(unit: str, size: int, separators: tuple[re.Pattern[str], ...] = SEPARATORS) -> list[str]:
    """Break a unit into pieces of at most `size` characters, preferring natural boundaries."""
    if len(unit) <= size:
        return [unit]
    if not separators:
        return [unit[start : start + size] for start in range(0, len(unit), size)]
    separator, rest = separators[0], separators[1:]
    pieces: list[str] = []
    for part in separator.split(unit):
        part = part.strip()
        if part:
            pieces.extend(_fit(part, size, rest))
    return pieces


def _pack(pieces: list[str], size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    def length(items: list[str]) -> int:
        return sum(len(item) for item in items) + max(len(items) - 1, 0)

    for piece in pieces:
        if current and length([*current, piece]) > size:
            chunks.append(" ".join(current))
            current = _tail(current, overlap)
            # The carried-over tail must leave room for the new piece.
            while current and length([*current, piece]) > size:
                current.pop(0)
        current.append(piece)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _tail(items: list[str], overlap: int) -> list[str]:
    tail: list[str] = []
    total = 0
    for item in reversed(items):
        total += len(item) + (1 if tail else 0)
        if total > overlap:
            break
        tail.insert(0, item)
    return tail
