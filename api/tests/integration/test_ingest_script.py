import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.settings import ChunkingConfig, CorporaConfig, EmbeddingModelConfig, load_settings
from app.db.base import Base
from app.services.rag.context import RagContext
from app.services.rag.vector_store.pgvector import PgVectorStore
from scripts import ingest
from tests.helpers import make_registry
from tests.rag_helpers import PENGUINS


class TestIngestScript(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.engine = engine
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        Path(folder.name, "a.txt").write_text(PENGUINS)
        Path(folder.name, "broken.pdf").write_bytes(b"nope")
        settings = load_settings()
        settings.rag.embedding_models = {
            "fake-a": EmbeddingModelConfig(provider="fake", model="m", dimensions=64)
        }
        settings.rag.default_embedding = "fake-a"
        settings.rag.chunking_strategies = {
            "small": ChunkingConfig(method="fixed", size=40, overlap=5)
        }
        settings.rag.default_chunking = "small"
        settings.corpora = CorporaConfig.model_validate(
            {
                "corpora": [
                    {
                        "name": "handbook",
                        "source": {"type": "filesystem", "path": folder.name},
                    },
                    {"name": "empty", "source": {"type": "filesystem", "path": folder.name + "/x"}},
                ]
            }
        )
        self.ctx = RagContext(settings, make_registry(), PgVectorStore())

    def run_script(self, names, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with Session(self.engine) as db, redirect_stdout(out), redirect_stderr(err):
            code = ingest.run(db, self.ctx, names, kwargs.get("embedding"), kwargs.get("chunking"))
        return code, out.getvalue(), err.getvalue()

    def test_ingests_a_configured_corpus_and_reports_failed_files(self):
        code, out, err = self.run_script(["handbook"])

        self.assertEqual(code, 1)  # one file could not be read
        self.assertIn("handbook: indexed 1 file(s) with fake-a / small", out)
        self.assertIn("failed: broken.pdf", err)

    def test_unknown_corpus_names_are_rejected(self):
        code, _, err = self.run_script(["nope"])

        self.assertEqual(code, 1)
        self.assertIn("not defined in corpora.yaml: nope", err)

    def test_selection_errors_and_missing_directories_are_reported(self):
        code, _, err = self.run_script(["empty"])
        self.assertEqual(code, 1)
        self.assertIn("empty: The corpus source directory does not exist", err)

        code, _, err = self.run_script(["handbook"], embedding="nope")
        self.assertEqual(code, 1)
        self.assertIn("Unknown embedding model", err)

    def test_main_parses_arguments_and_uses_the_configured_corpora(self):
        calls = []
        with (
            patch.object(ingest, "get_settings", return_value=self.ctx.settings),
            patch.object(ingest, "get_registry", return_value=self.ctx.registry),
            patch.object(ingest, "get_engine", return_value=self.engine),
            patch.object(ingest, "load_env"),
            patch.object(ingest, "run", side_effect=lambda *args: calls.append(args) or 0),
        ):
            self.assertEqual(ingest.main(["--all", "--embedding", "fake-a"]), 0)
            self.assertEqual(ingest.main(["--corpus", "handbook", "--chunking", "small"]), 0)

        self.assertEqual(calls[0][2:], (["handbook", "empty"], "fake-a", None))
        self.assertEqual(calls[1][2:], (["handbook"], None, "small"))


if __name__ == "__main__":
    unittest.main()
