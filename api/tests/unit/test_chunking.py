import unittest

from app.core.settings import ChunkingConfig
from app.services.rag.chunking import split_text

PARAGRAPHS = "\n\n".join(
    f"Paragraph {n} starts here. It has a second sentence! And a third one? Yes, a third." * 2
    for n in range(6)
)


def config(method, size=120, overlap=20):
    return ChunkingConfig(method=method, size=size, overlap=overlap)


class TestSplitText(unittest.TestCase):
    def test_blank_text_has_no_chunks(self):
        for method in ("fixed", "recursive", "paragraph", "sentence"):
            with self.subTest(method=method):
                self.assertEqual(split_text("  \n\n ", config(method)), [])

    def test_no_method_exceeds_the_size_and_none_loses_words(self):
        words = set(PARAGRAPHS.split())
        for method in ("fixed", "recursive", "paragraph", "sentence"):
            with self.subTest(method=method):
                chunks = split_text(PARAGRAPHS, config(method))

                self.assertGreater(len(chunks), 1)
                self.assertTrue(all(0 < len(c) <= 120 for c in chunks), method)
                if method != "fixed":  # a fixed window may cut words in half
                    self.assertEqual(set(" ".join(chunks).split()), words)

    def test_short_text_is_a_single_chunk(self):
        for method in ("fixed", "recursive", "paragraph", "sentence"):
            self.assertEqual(split_text("One short note.", config(method)), ["One short note."])

    def test_fixed_windows_overlap_by_the_configured_amount(self):
        text = "abcdefghijklmnopqrstuvwxyz"

        chunks = split_text(text, config("fixed", size=10, overlap=4))

        self.assertEqual(chunks, ["abcdefghij", "ghijklmnop", "mnopqrstuv", "stuvwxyz"])

    def test_paragraph_packs_whole_paragraphs_without_overlap(self):
        text = "First paragraph.\n\nSecond one.\n\nThird paragraph here."

        chunks = split_text(text, config("paragraph", size=32, overlap=0))

        self.assertEqual(chunks, ["First paragraph. Second one.", "Third paragraph here."])

    def test_paragraph_splits_an_oversized_paragraph(self):
        text = "word " * 40

        chunks = split_text(text, config("paragraph", size=50, overlap=0))

        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 50 for c in chunks))

    def test_sentence_chunks_end_on_sentence_boundaries_and_overlap(self):
        text = "Alpha is first. Beta is second. Gamma is third. Delta is fourth."

        chunks = split_text(text, config("sentence", size=34, overlap=16))

        self.assertEqual(
            chunks,
            [
                "Alpha is first. Beta is second.",
                "Beta is second. Gamma is third.",
                "Gamma is third. Delta is fourth.",
            ],
        )

    def test_overlap_is_trimmed_when_the_next_sentence_needs_the_room(self):
        text = "Short one. Short two. A considerably longer third sentence."

        chunks = split_text(text, config("sentence", size=40, overlap=25))

        self.assertEqual(chunks, ["Short one. Short two.", "A considerably longer third sentence."])

    def test_overlap_zero_never_repeats_text(self):
        chunks = split_text("One. Two. Three. Four.", config("sentence", size=10, overlap=0))

        self.assertEqual(chunks, ["One. Two.", "Three.", "Four."])

    def test_recursive_prefers_paragraph_boundaries(self):
        text = "Short one.\n\n" + "x" * 30 + "\n\nShort two."

        chunks = split_text(text, config("recursive", size=35, overlap=0))

        self.assertEqual(chunks, ["Short one.", "x" * 30, "Short two."])

    def test_recursive_cuts_an_unbroken_string_by_size(self):
        chunks = split_text("y" * 25, config("recursive", size=10, overlap=0))

        self.assertEqual(chunks, ["y" * 10, "y" * 10, "y" * 5])

    def test_different_methods_cut_the_same_text_differently(self):
        results = {
            m: split_text(PARAGRAPHS, config(m, size=300, overlap=0))
            for m in ("fixed", "paragraph", "sentence")
        }

        self.assertEqual(len({tuple(chunks) for chunks in results.values()}), 3)


if __name__ == "__main__":
    unittest.main()
