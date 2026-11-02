"""A source yields documents as (name, bytes) pairs; parsing and indexing happen elsewhere."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    name: str
    data: bytes


@dataclass(frozen=True)
class SourceFailure:
    """An item the source could not read. The rest of the source is still processed."""

    name: str
    reason: str


class Source(ABC):
    @abstractmethod
    def files(self) -> Iterator[SourceFile | SourceFailure]:
        """Yield every file this source offers, or why one of them could not be read."""
