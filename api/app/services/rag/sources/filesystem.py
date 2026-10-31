"""Every supported file under a directory (recursively)."""

from collections.abc import Iterator
from pathlib import Path

from app.services.rag.sources.base import Source, SourceFile


class FilesystemSource(Source):
    def __init__(self, root: Path, formats: list[str]) -> None:
        self.root = root
        self.formats = {f".{name}" for name in formats}

    def files(self) -> Iterator[SourceFile]:
        if not self.root.is_dir():
            raise FileNotFoundError(f"source directory {self.root} does not exist")
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix.lower() in self.formats:
                yield SourceFile(path.relative_to(self.root).as_posix(), path.read_bytes())
