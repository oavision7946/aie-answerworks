import unittest

from app.services.rag.parsers import ParseError, extension, parse
from tests.rag_helpers import pdf_bytes

FORMATS = ["pdf", "txt", "md"]


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

    def test_rejections_have_user_safe_messages(self):
        cases = {
            "a.docx": (b"x", "Unsupported file type"),
            "a.txt": (b"\xff\xfe\x00bad", "not valid UTF-8"),
            "b.txt": (b"   \n ", "no text"),
            "a.pdf": (b"not a pdf", "could not be read"),
        }
        for name, (data, message) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ParseError, message):
                parse(name, data, FORMATS)

    def test_a_format_must_be_enabled(self):
        with self.assertRaisesRegex(ParseError, "Unsupported"):
            parse("a.pdf", pdf_bytes("x"), ["txt"])


if __name__ == "__main__":
    unittest.main()
