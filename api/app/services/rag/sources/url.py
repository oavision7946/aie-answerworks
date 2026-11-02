"""Web pages and files fetched from a fixed list of http(s) addresses."""

import logging
from collections.abc import Iterator
from urllib.parse import urlsplit

import httpx

from app.services.rag.sources.base import Source, SourceFailure, SourceFile

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0
MAX_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 3

# File type to use when the address itself has no recognisable extension.
CONTENT_TYPES = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "txt",
    "text/markdown": "md",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def document_name(url: str, content_type: str, formats: list[str]) -> str:
    """A stable, readable name for a page: host and path, with an extension the parsers know."""
    parts = urlsplit(url)
    path = parts.path.strip("/") or "index"
    name = f"{parts.netloc}/{path}"
    extension = name.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if extension not in formats:
        name += "." + CONTENT_TYPES.get(content_type, "html")
    return name


class UrlSource(Source):
    def __init__(
        self, urls: list[str], formats: list[str], client: httpx.Client | None = None
    ) -> None:
        self.urls = urls
        self.formats = formats
        self.client = client

    def files(self) -> Iterator[SourceFile | SourceFailure]:
        owned = self.client is None
        client = self.client or httpx.Client(
            timeout=TIMEOUT_SECONDS, follow_redirects=True, max_redirects=MAX_REDIRECTS
        )
        try:
            for url in self.urls:
                yield self._fetch(client, url)
        finally:
            if owned:
                client.close()

    def _failed(self, url: str, reason: str) -> SourceFailure:
        return SourceFailure(document_name(url, "", self.formats), reason)

    def _fetch(self, client: httpx.Client, url: str) -> SourceFile | SourceFailure:
        try:
            with client.stream("GET", url) as response:
                if response.is_error:
                    return self._failed(url, f"The server answered {response.status_code}.")
                data = bytearray()
                for block in response.iter_bytes():
                    data.extend(block)
                    if len(data) > MAX_BYTES:
                        return self._failed(url, "The page is too large to ingest.")
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                body = bytes(data)
                if content_type.startswith("text/") or content_type == "application/xhtml+xml":
                    body = body.decode(response.encoding or "utf-8", errors="replace").encode()
        except httpx.HTTPError as exc:
            logger.warning("Could not fetch %s: %s", url, exc)
            return self._failed(url, "The address could not be fetched.")
        return SourceFile(document_name(url, content_type, self.formats), body)
