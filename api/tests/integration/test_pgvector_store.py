"""The pgvector ranking path. Runs only against a real PostgreSQL with the extension."""

import unittest

from alembic import command
from sqlalchemy import true
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentStatus, User
from app.db.session import create_db_engine
from app.services.llm.providers.fake import embed_text
from app.services.rag.vector_store.pgvector import PgVectorStore
from tests.integration.test_migrations import POSTGRES_URL, TestPostgresMigrations, alembic_config
from tests.unit.test_rag_core import RAG, resolve_spec


@unittest.skipUnless(POSTGRES_URL, "set TEST_POSTGRES_URL to run against PostgreSQL")
class TestPgVectorRanking(unittest.TestCase):
    def setUp(self):
        self.url = POSTGRES_URL
        TestPostgresMigrations._reset(self)
        command.upgrade(alembic_config(self.url), "head")
        self.engine = create_db_engine(self.url)
        self.addCleanup(TestPostgresMigrations._reset, self)
        self.addCleanup(self.engine.dispose)

    def test_cosine_ranking_runs_in_the_database_and_separates_embedding_models(self):
        store = PgVectorStore()
        a, b = resolve_spec(RAG, "a", "small"), resolve_spec(RAG, "b", "small")
        with Session(self.engine) as db:
            user = User(email="u@example.com", password_hash="x")
            db.add(user)
            db.flush()
            document = Document(
                owner_id=user.id,
                filename="f.txt",
                size_bytes=1,
                status=DocumentStatus.READY,
                text="t",
            )
            db.add(document)
            db.flush()
            for spec in (a, b):
                texts = ["penguins eat fish", "lava and magma"]
                dims = spec.embedding_dimensions
                store.add(db, document.id, spec, texts, [embed_text(t, dims) for t in texts])
            db.commit()

            hits = store.search(db, embed_text("penguins fish", 256), a, true(), 5)
            other = store.search(db, embed_text("penguins fish", 384), b, true(), 5)

            self.assertEqual(hits[0].chunk.text, "penguins eat fish")
            self.assertGreater(hits[0].score, hits[1].score)
            self.assertEqual(len(other), 2)

    def test_the_status_checks_see_the_schema_version_and_the_extension(self):
        from app.services import status_service

        database = status_service.database(self.engine)

        self.assertEqual(database.status, "ok")
        self.assertTrue(database.migrated)
        self.assertEqual(database.revision, database.head)
        self.assertIs(database.pgvector, True)


if __name__ == "__main__":
    unittest.main()
