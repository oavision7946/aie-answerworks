import unittest

from app.services.conversation_service import TITLE_LENGTH, title_from


class TestTitleFrom(unittest.TestCase):
    def test_short_messages_are_used_as_is(self):
        self.assertEqual(title_from("What is RAG?"), "What is RAG?")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(title_from("  a\n\n b\tc  "), "a b c")

    def test_long_messages_are_cut_with_an_ellipsis(self):
        title = title_from("word " * 40)

        self.assertEqual(len(title), TITLE_LENGTH)
        self.assertTrue(title.endswith("…"))

    def test_a_message_of_exactly_the_limit_is_not_cut(self):
        text = "x" * TITLE_LENGTH

        self.assertEqual(title_from(text), text)
