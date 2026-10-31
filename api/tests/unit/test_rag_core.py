"""Index descriptions, the embedder and the vector store, without HTTP."""

import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine, true
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.settings import ChunkingConfig, RagConfig
from app.db.base import Base
from app.db.models import Document, DocumentStatus
from app.services.llm.errors import ProviderError, TransientProviderError
from app.services.llm.providers.fake import embed_text
from app.services.rag.embeddings import BATCH_SIZE, build_embedder
from app.services.rag.errors import RagError
from app.services.rag.index import resolve_spec
from app.services.rag.vector_store.pgvector import PgVectorStore, cosine_similarity
from tests.helpers import fake_provider, make_registry

RAG = RagConfig.model_validate(
    {
        "embedding_models": {
            "a": {"provider": "fake", "model": "model-a", "dimensions": 256},
            "b": {"provider": "fake", "model": "model-b", "dimensions": 384},
        },
        "default_embedding": "a",
        "chunking_strategies": {
            "small": {"method": "recursive", "size": 100, "overlap": 10},
            "big": {"method": "paragraph", "size": 500, "overlap": 0},
        },
        "default_chunking": "small",
        "retrieval": {"top_k": 3, "min_score": 0.0},
        "vector_store": {"type": "pgvector"},
        "supported_formats": ["txt"],
    }
)


class TestIndexSpec(unittest.TestCase):
    def test_defaults_fill_in_omitted_names(self):
        spec = resolve_spec(RAG, None, None)

        self.assertEqual(
            spec.chunk_fields(),
            {
                "embedding_name": "a",
                "embedding_provider": "fake",
                "embedding_model": "model-a",
                "embedding_dimensions": 256,
                "chunking_name": "small",
                "chunking_method": "recursive",
                "chunk_size": 100,
                "chunk_overlap": 10,
            },
        )

    def test_names_are_labels_and_do_not_affect_comparability(self):
        renamed = RAG.model_copy(deep=True)
        renamed.embedding_models["renamed"] = renamed.embedding_models["a"]
        renamed.chunking_strategies["other"] = renamed.chunking_strategies["small"]

        self.assertEqual(
            resolve_spec(RAG, "a", "small").match_fields(),
            resolve_spec(renamed, "renamed", "other").match_fields(),
        )
        self.assertNotEqual(
            resolve_spec(RAG, "a", "small").match_fields(),
            resolve_spec(RAG, "b", "small").match_fields(),
        )
        self.assertNotEqual(
            resolve_spec(RAG, "a", "small").match_fields(),
            resolve_spec(RAG, "a", "big").match_fields(),
        )

    def test_chunking_config_round_trips(self):
        self.assertEqual(
            resolve_spec(RAG, "a", "big").chunking,
            ChunkingConfig(method="paragraph", size=500, overlap=0),
        )

    def test_unknown_names_are_rejected(self):
        with self.assertRaisesRegex(RagError, "embedding model 'x'") as caught:
            resolve_spec(RAG, "x", None)
        self.assertEqual(caught.exception.status_code, 422)
        with self.assertRaisesRegex(RagError, "chunking strategy 'x'"):
            resolve_spec(RAG, None, "x")


class TestEmbedder(unittest.TestCase):
    def setUp(self):
        self.provider = fake_provider()
        self.registry = make_registry(self.provider)
        self.spec = resolve_spec(RAG, "a", "small")

    def test_batches_requests_and_keeps_order(self):
        texts = [f"text {i}" for i in range(BATCH_SIZE + 1)]

        vectors = build_embedder(self.registry, self.spec).embed(texts)

        self.assertEqual([len(texts) for _, texts in self.provider.embed_calls], [BATCH_SIZE, 1])
        self.assertEqual(self.provider.embed_calls[0][0], "model-a")
        self.assertEqual(vectors[-1], embed_text("text 64", 256))

    def test_provider_that_is_not_running_is_a_503(self):
        spec = resolve_spec(RAG, "a", "small")
        spec = type(spec)(**{**spec.chunk_fields(), "embedding_provider": "missing"})

        with self.assertRaises(RagError) as caught:
            build_embedder(self.registry, spec)
        self.assertEqual(caught.exception.status_code, 503)

    def test_transient_failures_are_retried_then_reported_as_unavailable(self):
        def fail(*args, **kwargs):
            raise TransientProviderError("down")

        with patch.object(self.provider, "embed", fail), patch("time.sleep"):
            with self.assertRaises(RagError) as caught:
                build_embedder(self.registry, self.spec).embed(["a"])
        self.assertEqual(caught.exception.status_code, 503)

    def test_other_failures_do_not_leak_details(self):
        def fail(*args, **kwargs):
            raise ProviderError("secret detail")

        with patch.object(self.provider, "embed", fail):
            with self.assertRaises(RagError) as caught:
                build_embedder(self.registry, self.spec).embed(["a"])
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("secret", caught.exception.detail)

    def test_vectors_of_the_wrong_length_are_refused(self):
        spec = type(self.spec)(**{**self.spec.chunk_fields(), "embedding_dimensions": 99})
        self.provider.embed = lambda model, texts, dimensions=None: [[0.0] * 3 for _ in texts]

        with self.assertRaises(RagError) as caught:
            build_embedder(self.registry, spec).embed(["a"])
        self.assertEqual(caught.exception.status_code, 502)


class TestFakeEmbeddings(unittest.TestCase):
    def test_deterministic_normalised_and_word_based(self):
        a, b, c = (embed_text(t, 256) for t in ("penguins eat fish", "fish eat penguins", "lava"))

        self.assertEqual(a, embed_text("penguins eat fish", 256))
        self.assertAlmostEqual(cosine_similarity(a, a), 1.0)
        self.assertAlmostEqual(cosine_similarity(a, b), 1.0)  # same words, any order
        self.assertLess(cosine_similarity(a, c), 0.5)
        self.assertEqual(embed_text("", 4), [0.0] * 4)
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 0.0]), 0.0)


class TestVectorStore(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = Session(engine)
        self.addCleanup(self.db.close)
        self.store = PgVectorStore()
        # SQLite does not enforce foreign keys, so the owner need not exist for ranking tests.
        self.document = Document(
            owner_id=uuid.uuid4(),
            filename="f.txt",
            size_bytes=1,
            status=DocumentStatus.READY,
            text="t",
        )
        self.db.add(self.document)
        self.db.commit()
        self.spec_a = resolve_spec(RAG, "a", "small")
        self.spec_b = resolve_spec(RAG, "b", "small")

    def add(self, spec, texts):
        dims = spec.embedding_dimensions
        self.store.add(self.db, self.document.id, spec, texts, [embed_text(t, dims) for t in texts])
        self.db.commit()

    def test_search_ranks_by_similarity_and_records_the_index_on_each_chunk(self):
        self.add(self.spec_a, ["penguins eat fish", "lava and magma", "fish and chips"])

        hits = self.store.search(
            self.db, embed_text("penguins fish", 256), self.spec_a, true(), top_k=2
        )

        self.assertEqual([h.chunk.text for h in hits], ["penguins eat fish", "fish and chips"])
        self.assertGreater(hits[0].score, hits[1].score)
        chunk = hits[0].chunk
        self.assertEqual(
            (chunk.embedding_name, chunk.embedding_model, chunk.embedding_dimensions),
            ("a", "model-a", 256),
        )
        self.assertEqual(
            (chunk.chunking_name, chunk.chunking_method, chunk.chunk_size, chunk.chunk_overlap),
            ("small", "recursive", 100, 10),
        )

    def test_search_only_compares_vectors_from_the_same_index(self):
        self.add(self.spec_a, ["penguins eat fish"])
        self.add(self.spec_b, ["penguins eat fish", "lava"])

        in_a = self.store.search(self.db, embed_text("penguins", 256), self.spec_a, true(), 10)
        in_b = self.store.search(self.db, embed_text("penguins", 384), self.spec_b, true(), 10)
        in_big = self.store.search(
            self.db, embed_text("penguins", 256), resolve_spec(RAG, "a", "big"), true(), 10
        )

        self.assertEqual((len(in_a), len(in_b), len(in_big)), (1, 2, 0))

    def test_delete_removes_one_index_or_all(self):
        self.add(self.spec_a, ["one"])
        self.add(self.spec_b, ["two"])

        self.store.delete(self.db, self.document.id, self.spec_a)
        remaining = self.store.search(self.db, embed_text("two", 384), self.spec_b, true(), 10)
        gone = self.store.search(self.db, embed_text("one", 256), self.spec_a, true(), 10)
        self.store.delete(self.db, self.document.id)
        nothing = self.store.search(self.db, embed_text("two", 384), self.spec_b, true(), 10)

        self.assertEqual((len(remaining), len(gone), len(nothing)), (1, 0, 0))


if __name__ == "__main__":
    unittest.main()
