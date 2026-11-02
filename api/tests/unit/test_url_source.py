import unittest

import httpx

from app.services.rag.sources.base import SourceFailure, SourceFile
from app.services.rag.sources.url import MAX_BYTES, UrlSource, document_name

FORMATS = ["pdf", "txt", "md", "docx", "html", "htm"]


def fetch(handler, urls) -> list[SourceFile | SourceFailure]:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return list(UrlSource(urls, FORMATS, client).files())


class TestDocumentName(unittest.TestCase):
    def test_names_are_host_and_path_with_a_known_extension(self):
        cases = [
            ("https://example.com/docs/guide.html", "text/html", "example.com/docs/guide.html"),
            ("https://example.com/docs/guide", "text/html", "example.com/docs/guide.html"),
            ("https://example.com/", "text/html", "example.com/index.html"),
            ("https://example.com/notes", "text/plain", "example.com/notes.txt"),
            ("https://example.com/a/report.pdf", "application/pdf", "example.com/a/report.pdf"),
            ("https://example.com/feed", "application/json", "example.com/feed.html"),
            ("https://example.com/v1.2/page", "text/markdown", "example.com/v1.2/page.md"),
        ]
        for url, content_type, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(document_name(url, content_type, FORMATS), expected)


class TestUrlSource(unittest.TestCase):
    def test_pages_are_fetched_and_named(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/a":
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>A</p>")
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

        files = fetch(handler, ["https://example.com/a", "https://example.com/b.pdf"])

        self.assertEqual(
            files,
            [
                SourceFile("example.com/a.html", b"<p>A</p>"),
                SourceFile("example.com/b.pdf", b"%PDF"),
            ],
        )

    def test_text_in_another_charset_is_converted_to_utf8(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=iso-8859-1"},
                content="café".encode("latin-1"),
            )

        (file,) = fetch(handler, ["https://example.com/n"])

        self.assertEqual(file, SourceFile("example.com/n.txt", "café".encode()))

    def test_failures_are_reported_per_address_and_do_not_stop_the_rest(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/missing":
                return httpx.Response(404)
            if request.url.path == "/down":
                raise httpx.ConnectError("refused")
            if request.url.path == "/huge":
                return httpx.Response(200, content=b"x" * (MAX_BYTES + 1))
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="fine")

        files = fetch(
            handler,
            [f"https://example.com/{p}" for p in ("missing", "down", "huge", "ok")],
        )

        self.assertEqual(
            files,
            [
                SourceFailure("example.com/missing.html", "The server answered 404."),
                SourceFailure("example.com/down.html", "The address could not be fetched."),
                SourceFailure("example.com/huge.html", "The page is too large to ingest."),
                SourceFile("example.com/ok.txt", b"fine"),
            ],
        )

    def test_without_a_client_one_is_created_and_closed(self):
        source = UrlSource([], FORMATS)
        self.assertEqual(list(source.files()), [])


if __name__ == "__main__":
    unittest.main()
