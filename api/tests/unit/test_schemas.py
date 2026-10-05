import unittest

from pydantic import ValidationError

from app.schemas.ask import AskRequest, ModelOutput


class TestAskRequest(unittest.TestCase):
    def test_defaults(self):
        request = AskRequest(question="  why?  ")

        self.assertEqual(request.question, "why?")
        self.assertIsNone(request.model)
        self.assertIsNone(request.provider)
        self.assertFalse(request.stream)
        self.assertFalse(request.force_bad_first_response)

    def test_rejects_blank_question_unknown_model_and_extras(self):
        for payload in (
            {"question": " "},
            {"question": ""},
            {"question": "Hi", "model": 5},
            {"question": "Hi", "provider": 5},
            {"question": "Hi", "extra": True},
            {"question": 5},
            {"question": "Hi", "stream": "yes"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                AskRequest(**payload)


class TestModelOutput(unittest.TestCase):
    def test_strips_answer(self):
        self.assertEqual(ModelOutput(answer=" hi ").answer, "hi")

    def test_rejects_blank_answer(self):
        for answer in ("", "   "):
            with self.subTest(answer=answer), self.assertRaises(ValidationError):
                ModelOutput(answer=answer)


if __name__ == "__main__":
    unittest.main()
