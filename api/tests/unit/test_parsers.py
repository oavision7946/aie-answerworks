import io
import unittest
import zipfile
from unittest import mock

from app.services.rag import parsers
from app.services.rag.parsers import ParseError, extension, parse
from tests.rag_helpers import docx_bytes, pdf_bytes

FORMATS = ["pdf", "txt", "md", "docx", "html", "htm"]
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class TestParse(unittest.TestCase):
    def test_extension_is_lowercase_without_dot(self):
        self.assertEqual(extension("Report.FINAL.PDF"), "pdf")
        self.assertEqual(extension("noextension"), "")

    def test_text_and_markdown(self):
        self.assertEqual(parse("a.txt", b"  hello  \n", FORMATS), "hello")
        self.assertEqual(parse("A.MD", b"# Title\n\nbody", FORMATS), "# Title\n\nbody")

    def test_utf8_bom_is_removed_and_nul_bytes_dropped(self):
        self.assertEqual(parse("a.txt", b"\xef\xbb\xbfcaf\xc3\xa9\x00", FORMATS), "café")

    def test_pdf_text_layer(self):
        self.assertEqual(parse("a.pdf", pdf_bytes("Hello from a PDF"), FORMATS), "Hello from a PDF")

    def test_docx_paragraphs_tabs_and_line_breaks(self):
        xml = (
            f'<w:document xmlns:w="{NS}"><w:body>'
            "<w:p><w:r><w:t>First</w:t><w:tab/><w:t>col</w:t><w:br/><w:t>next</w:t></w:r></w:p>"
            "<w:p></w:p>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>In a table</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            "</w:body></w:document>"
        ).encode()
        text = parse("a.docx", docx_bytes(document_xml=xml), FORMATS)
        self.assertEqual(text, "First\tcol\nnext\n\nIn a table")
        self.assertEqual(parse("b.DOCX", docx_bytes("One", "Two"), FORMATS), "One\n\nTwo")

    def test_html_keeps_visible_text_and_drops_scripts_and_markup(self):
        page = (
            b"<html><head><title> My  page </title><style>p{}</style></head><body>"
            b"<nav>Menu</nav><h1>Penguins</h1><p>They eat <b>fish</b> &amp; krill.</p>"
            b"<script>var x = 1;</script><ul><li>one</li><li>two</li></ul></body></html>"
        )
        text = parse("page.html", page, FORMATS)
        self.assertEqual(text, "My page\n\nMenu\n\nPenguins\n\nThey eat fish & krill.\n\none\ntwo")
        self.assertEqual(parse("a.htm", b"<p>Only body</p>", FORMATS), "Only body")
        self.assertEqual(parse("t.html", b"<title>Just a title</title>", FORMATS), "Just a title")

    def test_rejections_have_user_safe_messages(self):
        cases = {
            "a.xlsx": (b"x", "Unsupported file type"),
            "a.txt": (b"\xff\xfe\x00bad", "not valid UTF-8"),
            "b.txt": (b"   \n ", "no text"),
            "a.pdf": (b"not a pdf", "could not be read"),
            "a.docx": (b"not a zip", "Word document could not be read"),
            "b.docx": (self.zip_without_document(), "Word document could not be read"),
            "c.docx": (docx_bytes(document_xml=b"<w:p"), "Word document could not be read"),
            "d.docx": (
                docx_bytes(document_xml=b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'),
                "Word document could not be read",
            ),
            "e.docx": (docx_bytes(" "), "no text"),
            "a.html": (b"\xff\xfe<p>x</p>", "not valid UTF-8"),
            "b.html": (b"<script>only code</script>", "no text"),
        }
        for name, (data, message) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ParseError, message):
                parse(name, data, FORMATS)

    @staticmethod
    def zip_without_document() -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("other.xml", "<x/>")
        return out.getvalue()

    def test_an_oversized_word_document_is_refused(self):
        with mock.patch.object(parsers, "MAX_DOCX_XML_BYTES", 10):
            with self.assertRaisesRegex(ParseError, "too large"):
                parse("big.docx", docx_bytes("A paragraph that is longer than ten bytes"), FORMATS)

    def test_a_format_must_be_enabled(self):
        with self.assertRaisesRegex(ParseError, "Unsupported"):
            parse("a.pdf", pdf_bytes("x"), ["txt"])


if __name__ == "__main__":
    unittest.main()
