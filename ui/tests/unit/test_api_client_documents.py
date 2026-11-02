"""Document, corpus and retrieval calls of the API client."""

import json
import unittest

import respx

from app import config
from app.clients import api_client
from app.clients.api_client import AuthExpired, RagChoice
from tests.app.helpers import CORPUS, INDEX, RAG_OPTIONS, STATUS

BASE = config.API_BASE_URL.rstrip("/")
GPT = api_client.ModelInfo(provider="openai", id="gpt-4o", label="GPT-4o")
DOC = {
    "id": "d-1",
    "filename": "notes.txt",
    "size_bytes": 20,
    "status": "ready",
    "error": None,
    "owner_id": "u-1",
    "corpus_id": None,
    "created_at": "2026-10-31T10:00:00Z",
    "indexes": [INDEX],
}
CITATION = {
    "chunk_id": "c-1",
    "document_id": "d-1",
    "filename": "notes.txt",
    "chunk_index": 0,
    "text": "Penguins live in Antarctica.",
    "score": 0.82,
    "embedding_name": "small",
    "chunking_name": "recursive",
}
CHAT = {
    "conversation_id": "c-1",
    "message_id": "m-1",
    "answer": "Antarctica [1]",
    "provider": "openai",
    "model": "gpt-4o",
    "tokens_used": 5,
    "latency_ms": 3,
    "cost_usd": None,
    "citations": [CITATION],
}


def sent(route) -> dict:
    return json.loads(route.calls.last.request.content)


class TestChatWithDocuments(unittest.TestCase):
    @respx.mock
    def test_rag_choice_adds_retrieval_fields_to_the_payload(self):
        route = respx.post(f"{BASE}/chat").respond(json=CHAT)

        result = api_client.chat(
            "q", GPT, "c-9", RagChoice(embedding="large", chunking="sentence"), token="t"
        )

        self.assertEqual(
            sent(route),
            {
                "message": "q",
                "model": "gpt-4o",
                "provider": "openai",
                "conversation_id": "c-9",
                "use_rag": True,
                "embedding": "large",
                "chunking": "sentence",
            },
        )
        self.assertEqual(result.citations[0].filename, "notes.txt")
        self.assertEqual(result.citations[0].score, 0.82)

    @respx.mock
    def test_an_empty_corpus_list_is_sent_but_none_is_omitted(self):
        route = respx.post(f"{BASE}/chat").respond(json=CHAT)

        api_client.chat("q", GPT, None, RagChoice(corpus_ids=[]))
        self.assertEqual(sent(route)["corpus_ids"], [])
        api_client.chat("q", GPT, None, RagChoice())
        self.assertNotIn("corpus_ids", sent(route))

    @respx.mock
    def test_without_rag_the_payload_is_unchanged(self):
        route = respx.post(f"{BASE}/chat").respond(json=CHAT)

        api_client.chat("q", GPT, None)

        self.assertEqual(sent(route), {"message": "q", "model": "gpt-4o", "provider": "openai"})

    @respx.mock
    def test_streaming_passes_the_choice_and_returns_citations(self):
        body = (
            f'event: delta\ndata: {{"content": "Hi"}}\n\nevent: done\ndata: {json.dumps(CHAT)}\n\n'
        )
        route = respx.post(f"{BASE}/chat").respond(
            text=body, headers={"content-type": "text/event-stream"}
        )

        result = api_client.chat_streaming("q", GPT, None, lambda text: None, RagChoice())

        self.assertTrue(sent(route)["use_rag"])
        self.assertTrue(sent(route)["stream"])
        self.assertEqual(result.citations[0].chunk_id, "c-1")


class TestDocuments(unittest.TestCase):
    @respx.mock
    def test_options(self):
        respx.get(f"{BASE}/rag/options").respond(json=RAG_OPTIONS)

        options = api_client.get_rag_options("t")

        self.assertEqual(options.default_embedding, "small")
        self.assertEqual(options.embedding_models[0].display, "small · emb-small (8d)")
        self.assertEqual(options.chunking_strategies[1].display, "sentence · sentence 500/100")
        self.assertFalse(options.embedding_models[2].available)

    @respx.mock
    def test_upload_sends_multipart_with_the_choices(self):
        route = respx.post(f"{BASE}/documents").respond(201, json=DOC)

        doc = api_client.upload_document("notes.txt", b"hello", "small", "recursive", "k-1", "t")

        request = route.calls.last.request
        self.assertTrue(request.headers["content-type"].startswith("multipart/form-data"))
        body = request.content.decode()
        for expected in ('name="file"; filename="notes.txt"', "hello", "small", "recursive", "k-1"):
            self.assertIn(expected, body)
        self.assertEqual(request.headers["authorization"], "Bearer t")
        self.assertEqual(doc.indexes[0].chunk_count, 3)

    @respx.mock
    def test_upload_without_choices_sends_only_the_file(self):
        route = respx.post(f"{BASE}/documents").respond(201, json=DOC)

        api_client.upload_document("notes.txt", b"hello")

        body = route.calls.last.request.content.decode()
        self.assertNotIn('name="embedding"', body)
        self.assertNotIn('name="corpus_id"', body)

    @respx.mock
    def test_list_documents_for_me_or_a_corpus(self):
        mine = respx.get(f"{BASE}/documents").respond(json=[DOC])

        self.assertEqual(api_client.list_documents()[0].filename, "notes.txt")
        self.assertEqual(str(mine.calls.last.request.url), f"{BASE}/documents")
        api_client.list_documents("k-1")
        self.assertEqual(str(mine.calls.last.request.url), f"{BASE}/documents?corpus_id=k-1")

    @respx.mock
    def test_index_chunks_and_delete(self):
        index = respx.post(f"{BASE}/documents/d-1/index").respond(json=DOC)
        chunks = respx.get(f"{BASE}/documents/d-1/chunks").respond(
            json=[{**INDEX, "id": "c-1", "chunk_index": 0, "text": "t"}]
        )
        delete = respx.delete(f"{BASE}/documents/d-1").respond(204)

        api_client.index_document("d-1", "large", None)
        listed = api_client.list_chunks("d-1", 5)
        api_client.delete_document("d-1")

        self.assertEqual(sent(index), {"embedding": "large"})
        self.assertEqual(chunks.calls.last.request.url.params["limit"], "5")
        self.assertEqual(listed[0].embedding_name, "small")
        self.assertTrue(delete.called)

    @respx.mock
    def test_errors_use_the_api_message_and_expired_tokens_are_signalled(self):
        respx.post(f"{BASE}/documents").respond(422, json={"detail": "Unsupported file type."})
        with self.assertRaisesRegex(RuntimeError, "Unsupported file type"):
            api_client.upload_document("a.docx", b"x")
        respx.get(f"{BASE}/documents").respond(401, json={"detail": "expired"})
        with self.assertRaises(AuthExpired):
            api_client.list_documents()


class TestCorpora(unittest.TestCase):
    @respx.mock
    def test_corpus_management_calls(self):
        listing = respx.get(f"{BASE}/corpora").respond(json=[CORPUS])
        create = respx.post(f"{BASE}/corpora").respond(201, json=CORPUS)
        update = respx.patch(f"{BASE}/corpora/k-1").respond(json=CORPUS)
        delete = respx.delete(f"{BASE}/corpora/k-1").respond(204)

        self.assertEqual(api_client.list_corpora("t")[0].name, "handbook")
        api_client.create_corpus("handbook", "Policies", True)
        api_client.update_corpus("k-1", "New", False)
        api_client.delete_corpus("k-1")

        self.assertEqual(listing.calls.last.request.headers["authorization"], "Bearer t")
        self.assertEqual(
            sent(create), {"name": "handbook", "description": "Policies", "is_public": True}
        )
        self.assertEqual(sent(update), {"description": "New", "is_public": False})
        self.assertTrue(delete.called)

    @respx.mock
    def test_access_and_ingest_calls(self):
        user = {"id": "u-1", "email": "ana@example.com", "role": "user"}
        access = respx.get(f"{BASE}/corpora/k-1/access").respond(json=[user])
        grant = respx.post(f"{BASE}/corpora/k-1/access").respond(204)
        revoke = respx.delete(f"{BASE}/corpora/k-1/access/u-1").respond(204)
        ingest = respx.post(f"{BASE}/corpora/k-1/ingest").respond(
            json={
                "embedding_name": "small",
                "chunking_name": "recursive",
                "indexed": ["a.txt"],
                "failed": {"b.pdf": "bad"},
            }
        )

        self.assertEqual(api_client.list_corpus_access("k-1")[0].email, "ana@example.com")
        api_client.grant_access("k-1", "u-1")
        api_client.revoke_access("k-1", "u-1")
        result = api_client.ingest_corpus("k-1", "small", None)

        self.assertTrue(access.called and revoke.called)
        self.assertEqual(sent(grant), {"user_id": "u-1"})
        self.assertEqual(sent(ingest), {"embedding": "small"})
        self.assertEqual((result.indexed, result.failed), (["a.txt"], {"b.pdf": "bad"}))

    @respx.mock
    def test_system_status_is_parsed(self):
        route = respx.get(f"{BASE}/admin/status").respond(json=STATUS)

        status = api_client.get_system_status("tok")

        self.assertEqual(route.calls.last.request.headers["Authorization"], "Bearer tok")
        self.assertEqual((status.status, status.database.revision), ("ok", "0004"))
        self.assertEqual(status.providers[1].reason, "ANTHROPIC_API_KEY is not set")
        self.assertEqual(status.requests.by_status["2xx"], 38)

    @respx.mock
    def test_system_status_for_a_user_is_refused(self):
        respx.get(f"{BASE}/admin/status").respond(
            403, json={"detail": "Administrator access is required."}
        )

        with self.assertRaisesRegex(RuntimeError, "Administrator access"):
            api_client.get_system_status("tok")


if __name__ == "__main__":
    unittest.main()
