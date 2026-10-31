"""Documents page: private uploads and shared corpora in separate sections."""

import unittest

import respx

from app import config
from tests.app.helpers import CORPUS, INDEX, ONE, RAG_OPTIONS, new_app

BASE = config.API_BASE_URL.rstrip("/")
PAGE = "views/documents.py"
DOC = {
    "id": "d-1",
    "filename": "notes.txt",
    "size_bytes": 2048,
    "status": "ready",
    "error": None,
    "owner_id": "u-1",
    "corpus_id": None,
    "created_at": "2026-10-31T10:00:00Z",
    "indexes": [INDEX],
}
SHARED = {**DOC, "id": "d-2", "filename": "policy.md", "owner_id": None, "corpus_id": "k-1"}
BROKEN = {
    **SHARED,
    "id": "d-3",
    "filename": "scan.pdf",
    "status": "failed",
    "error": "bad",
    "indexes": [],
}


def labels(elements):
    return [e.label for e in elements]


class TestDocumentsPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        mock.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        self.mine = mock.get(f"{BASE}/documents").mock(
            side_effect=lambda request: respx.MockResponse(
                200,
                json=[SHARED] if request.url.params.get("corpus_id") else [DOC],
            )
        )
        mock.get(f"{BASE}/corpora").respond(json=[CORPUS])
        self.mock = mock

    def open(self):
        at = new_app().run()
        at.switch_page(PAGE).run()
        return at

    def test_private_uploads_and_shared_corpora_are_separate_sections(self):
        at = self.open()

        self.assertFalse(at.exception)
        headings = [m.value for m in at.markdown if m.value.startswith("###")]
        self.assertEqual(headings, ["### My uploads", "### Shared corpora"])
        expander_labels = labels(at.expander)
        self.assertEqual(
            expander_labels, ["notes.txt · 2.0 KB · ready", "policy.md · 2.0 KB · ready"]
        )
        corpus = next(s for s in at.selectbox if s.label == "Corpus")
        self.assertEqual(corpus.options[0], "handbook · 1 document(s)")

    def test_the_index_metadata_of_each_document_is_shown(self):
        at = self.open()

        rows = at.dataframe[0].value
        self.assertEqual(list(rows["Embedding"]), ["small"])
        self.assertEqual(list(rows["Model"]), ["emb-small (8d)"])
        self.assertEqual(list(rows["Method"]), ["recursive 800/120"])
        self.assertEqual(list(rows["Chunks"]), [3])

    def test_upload_sends_the_chosen_embedding_and_splitter(self):
        upload = self.mock.post(f"{BASE}/documents").respond(201, json=DOC)

        at = self.open()
        at.file_uploader[0].set_value(("notes.txt", b"hello there", "text/plain")).run()
        at.selectbox[0].select_index(1)  # large
        at.selectbox[1].select_index(1)  # sentence
        next(b for b in at.button if b.label == "Upload and index").click().run()

        self.assertFalse(at.exception)
        body = upload.calls.last.request.content.decode()
        for expected in ("hello there", 'name="embedding"', "large", 'name="chunking"', "sentence"):
            self.assertIn(expected, body)
        self.assertIn("Indexed notes.txt with large / sentence.", at.success[0].value)

    def test_unavailable_embedding_models_are_not_offered(self):
        at = self.open()

        self.assertEqual(
            [o for o in at.selectbox[0].options],
            ["small · emb-small (8d)", "large · emb-large (16d)"],
        )

    def test_upload_errors_are_shown(self):
        self.mock.post(f"{BASE}/documents").respond(
            422, json={"detail": "The file contains no text."}
        )

        at = self.open()
        at.file_uploader[0].set_value(("empty.txt", b" ", "text/plain")).run()
        next(b for b in at.button if b.label == "Upload and index").click().run()

        self.assertEqual(at.error[0].value, "The file contains no text.")

    def test_add_another_index(self):
        index = self.mock.post(f"{BASE}/documents/d-1/index").respond(json=DOC)

        at = self.open()
        next(b for b in at.button if b.label == "Index with these settings").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            index.calls.last.request.content, b'{"embedding":"small","chunking":"recursive"}'
        )
        self.assertIn("Indexed notes.txt", at.success[0].value)

    def test_index_errors_are_shown(self):
        self.mock.post(f"{BASE}/documents/d-1/index").respond(
            503, json={"detail": "The embedding model 'x' is not available on this server."}
        )

        at = self.open()
        next(b for b in at.button if b.label == "Index with these settings").click().run()

        self.assertIn("not available", at.error[0].value)

    def test_show_chunks_lists_text_and_metadata(self):
        self.mock.get(f"{BASE}/documents/d-1/chunks").respond(
            json=[{**INDEX, "id": "c-1", "chunk_index": 0, "text": "Penguins live in Antarctica."}]
        )

        at = self.open()
        next(b for b in at.button if b.label == "Show chunks").click().run()

        self.assertIn("#0 · small · recursive", " ".join(c.value for c in at.caption))
        self.assertIn("Penguins live in Antarctica.", [t.value for t in at.text])

    def test_delete_needs_confirmation(self):
        delete = self.mock.delete(f"{BASE}/documents/d-1").respond(204)

        at = self.open()
        next(b for b in at.button if b.label == "Delete").click().run()
        self.assertFalse(delete.called)
        self.assertIn("Delete this document", at.warning[0].value)
        next(b for b in at.button if b.label == "Yes, delete").click().run()

        self.assertTrue(delete.called)
        self.assertEqual(at.success[0].value, "Deleted notes.txt.")

    def test_cancel_keeps_the_document(self):
        delete = self.mock.delete(f"{BASE}/documents/d-1").respond(204)

        at = self.open()
        next(b for b in at.button if b.label == "Delete").click().run()
        next(b for b in at.button if b.label == "Cancel").click().run()

        self.assertFalse(delete.called)
        self.assertEqual(len(at.warning), 0)

    def test_delete_errors_are_shown(self):
        self.mock.delete(f"{BASE}/documents/d-1").respond(
            404, json={"detail": "Document not found."}
        )

        at = self.open()
        next(b for b in at.button if b.label == "Delete").click().run()
        next(b for b in at.button if b.label == "Yes, delete").click().run()

        self.assertEqual(at.error[0].value, "Document not found.")

    def test_shared_documents_are_read_only(self):
        at = self.open()

        shared = [b.label for b in at.button]
        self.assertEqual(shared.count("Delete"), 1)  # only the private upload
        self.assertEqual(shared.count("Index with these settings"), 1)

    def test_failed_files_show_their_reason(self):
        self.mine.mock(
            side_effect=lambda request: respx.MockResponse(
                200, json=[BROKEN] if request.url.params.get("corpus_id") else []
            )
        )

        at = self.open()

        self.assertIn("You have not uploaded anything yet.", [i.value for i in at.info])
        self.assertEqual(at.error[0].value, "bad")

    def test_no_corpora_message(self):
        self.mock.get(f"{BASE}/corpora").respond(json=[])

        at = self.open()

        self.assertIn("No shared corpora are available to you.", [i.value for i in at.info])

    def test_a_corpus_without_documents(self):
        self.mine.mock(side_effect=lambda request: respx.MockResponse(200, json=[]))

        at = self.open()

        self.assertIn("This corpus has no documents yet.", [i.value for i in at.info])

    def test_corpus_description_is_shown(self):
        at = self.open()

        self.assertIn("Policies", [c.value for c in at.caption])

    def test_page_explains_when_documents_are_unavailable(self):
        self.mock.get(f"{BASE}/rag/options").respond(500, json={"detail": "boom"})

        at = self.open()

        self.assertIn("Documents are not available", at.error[0].value)


if __name__ == "__main__":
    unittest.main()
