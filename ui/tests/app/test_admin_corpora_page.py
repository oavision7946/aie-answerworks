"""Admin → Corpora page, reached through the real navigation."""

import json
import unittest

import respx

from app import config
from tests.app.helpers import ADMIN_SIGNED_IN, CORPUS, INDEX, ONE, RAG_OPTIONS, new_app

BASE = config.API_BASE_URL.rstrip("/")
PAGE = "views/admin_corpora.py"
ROOT = {"id": "u-0", "email": "root@example.com", "role": "admin", "is_active": True}
ANA = {"id": "u-1", "email": "ana@example.com", "role": "user", "is_active": True}
DOC = {
    "id": "d-2",
    "filename": "policy.md",
    "size_bytes": 10,
    "status": "ready",
    "error": None,
    "owner_id": None,
    "corpus_id": "k-1",
    "created_at": "2026-10-31T10:00:00Z",
    "indexes": [INDEX],
}
BAD = {
    **DOC,
    "id": "d-3",
    "filename": "scan.pdf",
    "status": "failed",
    "error": "bad",
    "indexes": [],
}


def button(at, label):
    return next(b for b in at.button if b.label == label)


class TestAdminCorporaPage(unittest.TestCase):
    def setUp(self):
        mock = respx.mock(assert_all_called=False)
        mock.start()
        self.addCleanup(mock.stop)
        mock.get(f"{BASE}/models").respond(json=ONE)
        mock.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)
        self.corpora = mock.get(f"{BASE}/corpora").respond(json=[CORPUS])
        mock.get(f"{BASE}/admin/users").respond(json=[ROOT, ANA])
        self.access = mock.get(f"{BASE}/corpora/k-1/access").respond(json=[])
        mock.get(f"{BASE}/documents").respond(json=[DOC])
        self.mock = mock

    def open(self):
        at = new_app(auth=ADMIN_SIGNED_IN).run()
        at.switch_page(PAGE).run()
        return at

    def test_lists_corpora_with_visibility_and_documents(self):
        at = self.open()

        self.assertFalse(at.exception)
        self.assertEqual(at.expander[1].label, "handbook · restricted · 1 document(s)")
        self.assertTrue(
            any("policy.md · ready · small/recursive (3)" in m.value for m in at.markdown)
        )

    def test_create_corpus(self):
        create = self.mock.post(f"{BASE}/corpora").respond(201, json=CORPUS)

        at = self.open()
        at.text_input[0].set_value("handbook")
        at.text_input[1].set_value("Policies")
        at.checkbox[0].check()
        button(at, "Create corpus").click().run()

        self.assertFalse(at.exception)
        self.assertEqual(
            json.loads(create.calls.last.request.content),
            {"name": "handbook", "description": "Policies", "is_public": True},
        )
        self.assertEqual(at.success[0].value, "Created handbook.")

    def test_create_errors_are_shown(self):
        self.mock.post(f"{BASE}/corpora").respond(
            409, json={"detail": "A corpus with this name already exists."}
        )

        at = self.open()
        at.text_input[0].set_value("handbook")
        button(at, "Create corpus").click().run()

        self.assertIn("already exists", at.error[0].value)

    def test_first_corpus_form_is_open_when_there_are_none(self):
        self.corpora.respond(json=[])

        at = self.open()

        self.assertTrue(at.expander[0].proto.expanded)

    def test_save_settings(self):
        update = self.mock.patch(f"{BASE}/corpora/k-1").respond(json=CORPUS)

        at = self.open()
        next(c for c in at.checkbox if c.label == "Public").check()
        button(at, "Save settings").click().run()

        self.assertEqual(
            json.loads(update.calls.last.request.content),
            {"description": "Policies", "is_public": True},
        )
        self.assertEqual(at.success[0].value, "Updated handbook.")

    def test_save_errors_are_shown(self):
        self.mock.patch(f"{BASE}/corpora/k-1").respond(404, json={"detail": "Corpus not found."})

        at = self.open()
        button(at, "Save settings").click().run()

        self.assertEqual(at.error[0].value, "Corpus not found.")

    def test_grant_access_to_a_user_who_does_not_have_it_yet(self):
        grant = self.mock.post(f"{BASE}/corpora/k-1/access").respond(204)

        at = self.open()
        who = next(s for s in at.selectbox if s.label == "Grant access to")
        self.assertEqual(who.options, ["root@example.com", "ana@example.com"])
        who.select("ana@example.com")
        button(at, "Grant access").click().run()

        self.assertEqual(json.loads(grant.calls.last.request.content), {"user_id": "u-1"})
        self.assertEqual(at.success[0].value, "ana@example.com can now read handbook.")

    def test_granted_users_are_listed_and_can_be_revoked(self):
        self.access.respond(json=[ANA])
        revoke = self.mock.delete(f"{BASE}/corpora/k-1/access/u-1").respond(204)

        at = self.open()
        who = next(s for s in at.selectbox if s.label == "Grant access to")
        self.assertEqual(who.options, ["root@example.com"])  # ana already has it
        button(at, "Revoke").click().run()

        self.assertTrue(revoke.called)
        self.assertEqual(at.success[0].value, "ana@example.com can no longer read handbook.")

    def test_public_corpora_say_grants_are_not_needed(self):
        self.corpora.respond(json=[{**CORPUS, "is_public": True}])

        at = self.open()

        self.assertIn("It is public, so grants are not needed.", [c.value for c in at.caption])

    def test_upload_into_the_corpus_sends_the_corpus_id_and_choices(self):
        upload = self.mock.post(f"{BASE}/documents").respond(201, json=DOC)

        at = self.open()
        at.file_uploader[0].set_value(("policy.md", b"# Policy", "text/markdown")).run()
        embedding = next(s for s in at.selectbox if s.key == "corpus-k-1-embedding")
        embedding.select_index(1)
        button(at, "Upload and index").click().run()

        body = upload.calls.last.request.content.decode()
        for expected in ("# Policy", 'name="corpus_id"', "k-1", "large"):
            self.assertIn(expected, body)
        self.assertEqual(at.success[0].value, "Added policy.md to handbook.")

    def test_upload_errors_are_shown(self):
        self.mock.post(f"{BASE}/documents").respond(
            422, json={"detail": "The file contains no text."}
        )

        at = self.open()
        at.file_uploader[0].set_value(("empty.md", b" ", "text/markdown")).run()
        button(at, "Upload and index").click().run()

        self.assertEqual(at.error[0].value, "The file contains no text.")

    def test_ingest_the_source_folder(self):
        ingest = self.mock.post(f"{BASE}/corpora/k-1/ingest").respond(
            json={
                "embedding_name": "small",
                "chunking_name": "recursive",
                "indexed": ["a.txt", "b.md"],
                "failed": {"c.pdf": "The PDF could not be read."},
            }
        )

        at = self.open()
        button(at, "Ingest source folder").click().run()

        self.assertEqual(
            json.loads(ingest.calls.last.request.content),
            {"embedding": "small", "chunking": "recursive"},
        )
        message = at.success[0].value
        self.assertIn("Indexed 2 file(s) with small / recursive.", message)
        self.assertIn("c.pdf: The PDF could not be read.", message)

    def test_ingest_without_failures_has_no_failure_list(self):
        self.mock.post(f"{BASE}/corpora/k-1/ingest").respond(
            json={
                "embedding_name": "small",
                "chunking_name": "recursive",
                "indexed": ["a"],
                "failed": {},
            }
        )

        at = self.open()
        button(at, "Ingest source folder").click().run()

        self.assertNotIn("Failed", at.success[0].value)

    def test_ingest_errors_are_shown(self):
        self.mock.post(f"{BASE}/corpora/k-1/ingest").respond(
            422, json={"detail": "The corpus source directory does not exist on the server."}
        )

        at = self.open()
        button(at, "Ingest source folder").click().run()

        self.assertIn("does not exist", at.error[0].value)

    def test_corpora_without_a_source_have_no_ingest_button(self):
        self.corpora.respond(json=[{**CORPUS, "has_source": False}])

        at = self.open()

        self.assertNotIn("Ingest source folder", [b.label for b in at.button])

    def test_documents_show_status_and_can_be_deleted(self):
        delete = self.mock.delete(f"{BASE}/documents/d-2").respond(204)
        self.mock.get(f"{BASE}/documents").respond(json=[DOC, BAD])

        at = self.open()
        self.assertTrue(any("scan.pdf · failed — bad" in m.value for m in at.markdown))
        button(at, "Delete").click().run()

        self.assertTrue(delete.called)
        self.assertEqual(at.success[0].value, "Deleted policy.md.")

    def test_a_corpus_without_documents(self):
        self.mock.get(f"{BASE}/documents").respond(json=[])

        at = self.open()

        self.assertIn("No documents yet.", [c.value for c in at.caption])

    def test_delete_corpus_needs_confirmation(self):
        delete = self.mock.delete(f"{BASE}/corpora/k-1").respond(204)

        at = self.open()
        button(at, "Delete corpus").click().run()
        self.assertFalse(delete.called)
        self.assertIn("Delete this corpus", at.warning[0].value)
        button(at, "Yes, delete").click().run()

        self.assertTrue(delete.called)
        self.assertEqual(at.success[0].value, "Deleted handbook.")

    def test_cancelling_keeps_the_corpus(self):
        delete = self.mock.delete(f"{BASE}/corpora/k-1").respond(204)

        at = self.open()
        button(at, "Delete corpus").click().run()
        button(at, "Cancel").click().run()

        self.assertFalse(delete.called)
        self.assertEqual(len(at.warning), 0)

    def test_server_refusals_are_shown(self):
        self.corpora.respond(403, json={"detail": "Administrator access is required."})

        at = self.open()

        self.assertEqual(at.error[0].value, "Administrator access is required.")

    def test_documents_unavailable(self):
        self.mock.get(f"{BASE}/rag/options").respond(500, json={"detail": "boom"})

        at = self.open()

        self.assertIn("Documents are not available", at.error[0].value)


if __name__ == "__main__":
    unittest.main()
