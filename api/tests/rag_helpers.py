"""Fixtures for RAG tests: two fake embedding models, small chunking strategies, upload helpers."""

from app.core.settings import ChunkingConfig, EmbeddingModelConfig
from app.db.models import Role
from tests.chat_helpers import ChatTestCase

PENGUINS = "Penguins live in Antarctica and eat fish. Penguins huddle together to stay warm."
VOLCANOES = "Volcanoes erupt molten lava from magma chambers beneath the crust."


def pdf_bytes(text: str) -> bytes:
    """A minimal one-page PDF whose text layer is `text`."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


class RagTestCase(ChatTestCase):
    """Chat test app plus an admin and RAG settings that only use the fake provider."""

    def setUp(self):
        super().setUp()
        rag = self.settings.rag
        rag.embedding_models = {
            "fake-a": EmbeddingModelConfig(provider="fake", model="fake-embed-a", dimensions=256),
            "fake-b": EmbeddingModelConfig(provider="fake", model="fake-embed-b", dimensions=384),
            "offline": EmbeddingModelConfig(provider="local", model="nomic", dimensions=8),
        }
        rag.default_embedding = "fake-a"
        rag.chunking_strategies = {
            "small": ChunkingConfig(method="recursive", size=60, overlap=10),
            "para": ChunkingConfig(method="paragraph", size=200, overlap=0),
        }
        rag.default_chunking = "small"
        rag.retrieval.min_score = 0.0
        self.admin = self.add_user("admin@example.com", role=Role.ADMIN)

    def upload(self, user, name="penguins.txt", content=PENGUINS, **form):
        data = content if isinstance(content, bytes) else content.encode()
        return self.client.post(
            "/documents",
            files={"file": (name, data, "application/octet-stream")},
            data={k: str(v) for k, v in form.items()},
            headers=self.as_user(user),
        )

    def create_corpus(self, name="handbook", **body):
        response = self.client.post(
            "/corpora", json={"name": name, **body}, headers=self.as_user(self.admin)
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def search(self, user, query="where do penguins live", **body):
        return self.client.post(
            "/rag/search", json={"query": query, **body}, headers=self.as_user(user)
        )

    def hit_files(self, response) -> list[str]:
        self.assertEqual(response.status_code, 200, response.text)
        return [hit["filename"] for hit in response.json()["hits"]]
