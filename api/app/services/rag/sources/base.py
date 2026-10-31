"""A source yields documents as (name, bytes) pairs; parsing and indexing happen elsewhere."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    name: str
    data: bytes


class Source(ABC):
    @abstractmethod
    def files(self) -> Iterator[SourceFile]:
        """Yield every file this source offers."""
