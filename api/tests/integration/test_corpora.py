"""Shared corpora: admin management, grants, the public flag, ingestion and immediate revocation."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from app.core.settings import CorporaConfig
from app.services.rag import corpus_service
from app.services.rag.sources.url import UrlSource
from tests.rag_helpers import PENGUINS, VOLCANOES, RagTestCase, docx_bytes, pdf_bytes


class CorpusTestCase(RagTestCase):
    def as_admin(self):
        return self.as_user(self.admin)

    def grant(self, corpus, user):
        return self.client.post(
            f"/corpora/{corpus['id']}/access",
            json={"user_id": str(user.id)},
            headers=self.as_admin(),
        )

    def names(self, user) -> list[str]:
        response = self.client.get("/corpora", headers=self.as_user(user))
        self.assertEqual(response.status_code, 200)
        return [c["name"] for c in response.json()]


class TestAuthorizationMatrix(CorpusTestCase):
    def test_admin_routes_are_admin_only(self):
        corpus = self.create_corpus()
        cid, uid = corpus["id"], str(self.alice.id)
        routes = [
            ("post", "/corpora", {"name": "x"}),
            ("patch", f"/corpora/{cid}", {"is_public": True}),
            ("delete", f"/corpora/{cid}", None),
            ("get", f"/corpora/{cid}/access", None),
            ("post", f"/corpora/{cid}/access", {"user_id": uid}),
            ("delete", f"/corpora/{cid}/access/{uid}", None),
            ("post", f"/corpora/{cid}/ingest", {}),
        ]
        for method, path, body in routes:
            with self.subTest(route=f"{method} {path}"):
                call = getattr(self.client, method)
                kwargs = {"json": body} if body is not None else {}
                self.assertEqual(call(path, **kwargs).status_code, 401)
                self.assertEqual(
                    call(path, headers=self.as_user(self.alice), **kwargs).status_code, 403
                )
        self.assertEqual(self.client.get("/corpora").status_code, 401)

    def test_every_rag_route_needs_a_token(self):
        for method, path in (
            ("get", "/documents"),
            ("post", "/documents"),
            ("get", "/rag/options"),
            ("post", "/rag/search"),
        ):
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(getattr(self.client, method)(path).status_code, 401)


class TestManagement(CorpusTestCase):
    def test_create_update_list_and_delete(self):
        corpus = self.create_corpus("handbook", description="Policies", is_public=False)
        self.assertEqual(
            corpus,
            {
                "id": corpus["id"],
                "name": "handbook",
                "description": "Policies",
                "is_public": False,
                "document_count": 0,
                "has_source": False,
                "source_type": None,
                "refresh_minutes": None,
                "last_ingested_at": None,
                "last_ingest_error": None,
            },
        )

        updated = self.client.patch(
            f"/corpora/{corpus['id']}", json={"is_public": True}, headers=self.as_admin()
        )
        self.assertTrue(updated.json()["is_public"])
        self.assertEqual(updated.json()["description"], "Policies")

        self.upload(self.admin, corpus_id=corpus["id"])
        self.assertEqual(
            self.client.get("/corpora", headers=self.as_admin()).json()[0]["document_count"], 1
        )

        self.assertEqual(
            self.client.delete(f"/corpora/{corpus['id']}", headers=self.as_admin()).status_code, 204
        )
        self.assertEqual(self.names(self.admin), [])

    def test_duplicate_names_and_unknown_ids(self):
        self.create_corpus("handbook")
        missing = "00000000-0000-0000-0000-000000000000"

        duplicate = self.client.post("/corpora", json={"name": "handbook"}, headers=self.as_admin())

        self.assertEqual(duplicate.status_code, 409)
        for method, path, body in (
            ("patch", f"/corpora/{missing}", {"is_public": True}),
            ("delete", f"/corpora/{missing}", None),
            ("get", f"/corpora/{missing}/access", None),
            ("delete", f"/corpora/{missing}/access/{self.alice.id}", None),
            ("post", f"/corpora/{missing}/ingest", {}),
        ):
            with self.subTest(route=f"{method} {path}"):
                kwargs = {"json": body} if body is not None else {}
                response = getattr(self.client, method)(path, headers=self.as_admin(), **kwargs)
                self.assertEqual(response.status_code, 404)

    def test_description_can_change_on_its_own(self):
        corpus = self.create_corpus("handbook", is_public=True)

        updated = self.client.patch(
            f"/corpora/{corpus['id']}", json={"description": "New"}, headers=self.as_admin()
        ).json()

        self.assertEqual((updated["description"], updated["is_public"]), ("New", True))

    def test_granting_to_an_unknown_user_fails(self):
        corpus = self.create_corpus()

        response = self.client.post(
            f"/corpora/{corpus['id']}/access",
            json={"user_id": "00000000-0000-0000-0000-000000000000"},
            headers=self.as_admin(),
        )

        self.assertEqual(response.status_code, 404)

    def test_grants_are_listed_and_idempotent(self):
        corpus = self.create_corpus()
        self.grant(corpus, self.alice)
        self.grant(corpus, self.alice)

        granted = self.client.get(f"/corpora/{corpus['id']}/access", headers=self.as_admin())

        self.assertEqual([u["email"] for u in granted.json()], ["alice@example.com"])


class TestAccess(CorpusTestCase):
    def test_users_see_only_public_and_granted_corpora(self):
        granted = self.create_corpus("granted")
        self.create_corpus("public", is_public=True)
        self.create_corpus("secret")
        self.grant(granted, self.alice)

        self.assertEqual(self.names(self.alice), ["granted", "public"])
        self.assertEqual(self.names(self.bob), ["public"])
        self.assertEqual(self.names(self.admin), ["granted", "public", "secret"])

    def test_shared_documents_reach_only_users_with_access_and_revocation_is_immediate(self):
        corpus = self.create_corpus("handbook")
        self.upload(self.admin, "shared.txt", PENGUINS, corpus_id=corpus["id"])
        self.grant(corpus, self.alice)

        self.assertEqual(set(self.hit_files(self.search(self.alice))), {"shared.txt"})
        self.assertEqual(self.hit_files(self.search(self.bob)), [])

        self.client.delete(
            f"/corpora/{corpus['id']}/access/{self.alice.id}", headers=self.as_admin()
        )
        self.assertEqual(self.hit_files(self.search(self.alice)), [])

    def test_the_public_flag_opens_and_closes_a_corpus_for_everyone(self):
        corpus = self.create_corpus("handbook")
        self.upload(self.admin, "shared.txt", PENGUINS, corpus_id=corpus["id"])
        self.assertEqual(self.hit_files(self.search(self.bob)), [])

        self.client.patch(
            f"/corpora/{corpus['id']}", json={"is_public": True}, headers=self.as_admin()
        )
        self.assertEqual(set(self.hit_files(self.search(self.bob))), {"shared.txt"})

        self.client.patch(
            f"/corpora/{corpus['id']}", json={"is_public": False}, headers=self.as_admin()
        )
        self.assertEqual(self.hit_files(self.search(self.bob)), [])

    def test_search_combines_own_documents_with_shared_ones_and_can_narrow_corpora(self):
        one = self.create_corpus("one", is_public=True)
        two = self.create_corpus("two", is_public=True)
        self.upload(self.admin, "one.txt", PENGUINS, corpus_id=one["id"])
        self.upload(self.admin, "two.txt", PENGUINS, corpus_id=two["id"])
        self.upload(self.alice, "mine.txt", PENGUINS)

        everything = set(self.hit_files(self.search(self.alice)))
        narrowed = set(self.hit_files(self.search(self.alice, corpus_ids=[two["id"]])))
        none_shared = set(self.hit_files(self.search(self.alice, corpus_ids=[])))

        self.assertEqual(everything, {"one.txt", "two.txt", "mine.txt"})
        self.assertEqual(narrowed, {"two.txt", "mine.txt"})
        self.assertEqual(none_shared, {"mine.txt"})

    def test_listing_a_corpus_requires_access_and_hides_failures_from_users(self):
        corpus = self.create_corpus("handbook")
        self.upload(self.admin, "ok.txt", PENGUINS, corpus_id=corpus["id"])
        listing = lambda user: self.client.get(  # noqa: E731
            "/documents", params={"corpus_id": corpus["id"]}, headers=self.as_user(user)
        )

        self.assertEqual(listing(self.alice).status_code, 404)
        self.grant(corpus, self.alice)
        self.assertEqual([d["filename"] for d in listing(self.alice).json()], ["ok.txt"])
        self.assertEqual(
            self.client.get(
                "/documents",
                params={"corpus_id": "00000000-0000-0000-0000-000000000000"},
                headers=self.as_admin(),
            ).status_code,
            404,
        )

    def test_admins_manage_corpus_documents_but_users_cannot(self):
        corpus = self.create_corpus("handbook", is_public=True)
        document = self.upload(self.admin, "shared.txt", PENGUINS, corpus_id=corpus["id"]).json()
        url = f"/documents/{document['id']}"

        self.assertEqual(self.client.get(url, headers=self.as_user(self.alice)).status_code, 200)
        self.assertEqual(self.client.delete(url, headers=self.as_user(self.alice)).status_code, 404)
        self.assertEqual(
            self.client.post(
                f"{url}/index", json={"embedding": "fake-b"}, headers=self.as_admin()
            ).status_code,
            200,
        )
        self.assertEqual(self.client.delete(url, headers=self.as_admin()).status_code, 204)


class TestIngestion(CorpusTestCase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def corpus_from_config(self, path=None, name="handbook"):
        config = CorporaConfig.model_validate(
            {
                "corpora": [
                    {
                        "name": name,
                        "description": "Policies",
                        "public": True,
                        "source": {"type": "filesystem", "path": str(path or self.root)},
                    }
                ]
            }
        )
        with self.db_session() as db:
            return corpus_service.sync_configured(db, config)[name]

    def db_session(self):
        from sqlalchemy.orm import Session

        return Session(self.engine, expire_on_commit=False)

    def ingest(self, corpus, **body):
        return self.client.post(f"/corpora/{corpus.id}/ingest", json=body, headers=self.as_admin())

    def test_ingest_reads_supported_files_and_records_failures(self):
        (self.root / "penguins.txt").write_text(PENGUINS)
        (self.root / "sub").mkdir()
        (self.root / "sub" / "volcanoes.md").write_text(VOLCANOES)
        (self.root / "scan.pdf").write_bytes(b"not really a pdf")
        (self.root / "ignored.xlsx").write_bytes(b"x")
        corpus = self.corpus_from_config()

        response = self.ingest(corpus)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(sorted(body["indexed"]), ["penguins.txt", "sub/volcanoes.md"])
        self.assertEqual(list(body["failed"]), ["scan.pdf"])
        self.assertEqual((body["embedding_name"], body["chunking_name"]), ("fake-a", "small"))
        docs = self.client.get(
            "/documents", params={"corpus_id": str(corpus.id)}, headers=self.as_admin()
        ).json()
        status = {d["filename"]: d["status"] for d in docs}
        self.assertEqual(
            status, {"penguins.txt": "ready", "sub/volcanoes.md": "ready", "scan.pdf": "failed"}
        )
        self.assertEqual(self.names(self.bob), ["handbook"])  # public in corpora.yaml
        self.assertIn("penguins.txt", self.hit_files(self.search(self.bob)))

    def test_ingest_twice_updates_in_place_and_a_second_model_adds_an_index(self):
        (self.root / "penguins.txt").write_text(PENGUINS)
        corpus = self.corpus_from_config()
        self.ingest(corpus)
        (self.root / "penguins.txt").write_text("Penguins swim fast.")

        self.ingest(corpus)
        self.ingest(corpus, embedding="fake-b", chunking="para")

        [doc] = self.client.get(
            "/documents", params={"corpus_id": str(corpus.id)}, headers=self.as_admin()
        ).json()
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(
            {(i["embedding_name"], i["chunking_name"]) for i in doc["indexes"]},
            {("fake-a", "small"), ("fake-b", "para")},
        )
        chunks = self.client.get(f"/documents/{doc['id']}/chunks", headers=self.as_admin()).json()
        self.assertEqual({c["text"] for c in chunks}, {"Penguins swim fast."})

    def test_a_file_that_becomes_readable_clears_its_failure(self):
        (self.root / "notes.txt").write_bytes(b"\xff\xfe")
        corpus = self.corpus_from_config()
        self.assertIn("notes.txt", self.ingest(corpus).json()["failed"])

        (self.root / "notes.txt").write_text(PENGUINS)
        body = self.ingest(corpus).json()

        self.assertEqual((body["indexed"], body["failed"]), (["notes.txt"], {}))

    def test_an_embedding_failure_marks_the_file_failed_and_keeps_the_rest_of_the_run(self):
        (self.root / "a.txt").write_text(PENGUINS)
        corpus = self.corpus_from_config()
        self.assertEqual(self.ingest(corpus).json()["indexed"], ["a.txt"])
        self.provider.embed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        (self.root / "a.txt").write_text("Penguins changed their text.")

        body = self.ingest(corpus).json()

        self.assertEqual(list(body["failed"]), ["a.txt"])
        [doc] = self.client.get(
            "/documents", params={"corpus_id": str(corpus.id)}, headers=self.as_admin()
        ).json()
        self.assertEqual(doc["status"], "failed")

    def test_a_failed_document_cannot_be_reindexed(self):
        (self.root / "bad.txt").write_bytes(b"\xff\xfe")
        corpus = self.corpus_from_config()
        self.ingest(corpus)
        [doc] = self.client.get(
            "/documents", params={"corpus_id": str(corpus.id)}, headers=self.as_admin()
        ).json()

        response = self.client.post(
            f"/documents/{doc['id']}/index", json={}, headers=self.as_admin()
        )

        self.assertEqual(response.status_code, 409)

    def test_ingest_pdf(self):
        (self.root / "a.pdf").write_bytes(pdf_bytes("Penguins live in Antarctica"))
        corpus = self.corpus_from_config()

        self.assertEqual(self.ingest(corpus).json()["indexed"], ["a.pdf"])

    def test_corpus_without_a_source_or_with_a_missing_directory(self):
        manual = self.create_corpus("manual")
        missing = self.corpus_from_config(self.root / "nope", name="gone")

        no_source = self.client.post(
            f"/corpora/{manual['id']}/ingest", json={}, headers=self.as_admin()
        )
        no_dir = self.ingest(missing)

        self.assertEqual(no_source.status_code, 422)
        self.assertIn("no ingestion source", no_source.json()["detail"])
        self.assertEqual(no_dir.status_code, 422)

    def test_sync_updates_an_existing_corpus_and_resolves_relative_paths(self):
        first = self.corpus_from_config(self.root)
        again = self.corpus_from_config(self.root / "other")

        self.assertEqual(first.id, again.id)
        self.assertTrue(again.source_config["path"].endswith("other"))
        source = corpus_service.source_for(
            type(again)(name="r", source_config={"type": "filesystem", "path": "docs"}), ["txt"]
        )
        self.assertTrue(source.root.is_absolute())

    def test_embedding_that_is_unavailable_fails_before_reading_files(self):
        (self.root / "a.txt").write_text(PENGUINS)
        corpus = self.corpus_from_config()

        self.assertEqual(self.ingest(corpus, embedding="offline").status_code, 503)

    def corpus_info(self, corpus):
        listed = self.client.get("/corpora", headers=self.as_admin()).json()
        return next(c for c in listed if c["id"] == str(corpus.id))

    def test_files_that_did_not_change_are_not_embedded_again(self):
        (self.root / "a.txt").write_text(PENGUINS)
        (self.root / "b.txt").write_text(VOLCANOES)
        corpus = self.corpus_from_config()
        self.ingest(corpus)
        calls = []
        real_embed = self.provider.embed
        self.provider.embed = lambda *a, **k: calls.append(a) or real_embed(*a, **k)

        self.assertEqual(sorted(self.ingest(corpus).json()["indexed"]), ["a.txt", "b.txt"])
        self.assertEqual(calls, [])

        (self.root / "a.txt").write_text("Penguins changed.")
        self.ingest(corpus)
        self.assertEqual(len(calls), 1)  # only the edited file
        self.ingest(corpus, embedding="fake-b", chunking="para")  # a new index is still built
        self.assertEqual(len(calls), 3)

    def test_the_corpus_records_when_ingestion_ran_and_what_failed(self):
        (self.root / "a.txt").write_text(PENGUINS)
        corpus = self.corpus_from_config()
        self.assertIsNone(self.corpus_info(corpus)["last_ingested_at"])

        self.ingest(corpus)
        info = self.corpus_info(corpus)
        self.assertIsNotNone(info["last_ingested_at"])
        self.assertIsNone(info["last_ingest_error"])
        self.assertEqual(info["source_type"], "filesystem")

        for name in "bcde":
            (self.root / f"{name}.txt").write_bytes(b"\xff\xfe")
        self.ingest(corpus)
        self.assertEqual(
            self.corpus_info(corpus)["last_ingest_error"],
            "4 item(s) could not be ingested: b.txt, c.txt, d.txt and 1 more.",
        )

        self.provider.embed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
        (self.root / "a.txt").write_text("Penguins changed.")
        self.ingest(corpus)
        self.assertIn("could not be ingested", self.corpus_info(corpus)["last_ingest_error"])

    def test_a_missing_source_directory_is_recorded(self):
        corpus = self.corpus_from_config(self.root / "nope")

        self.ingest(corpus)

        self.assertEqual(
            self.corpus_info(corpus)["last_ingest_error"], "The source directory does not exist."
        )

    def test_word_and_web_files_are_ingested(self):
        (self.root / "policy.docx").write_bytes(docx_bytes("Penguins live in Antarctica."))
        (self.root / "page.html").write_text("<h1>Volcanoes</h1><p>Lava erupts.</p>")
        corpus = self.corpus_from_config()

        self.assertEqual(
            sorted(self.ingest(corpus).json()["indexed"]), ["page.html", "policy.docx"]
        )

    def url_corpus(self, handler, refresh_minutes=None):
        config = CorporaConfig.model_validate(
            {
                "corpora": [
                    {
                        "name": "web",
                        "public": True,
                        "refresh_minutes": refresh_minutes,
                        "source": {"type": "url", "urls": ["https://example.com/guide"]},
                    }
                ]
            }
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        patcher = mock.patch.object(
            corpus_service, "UrlSource", lambda urls, formats: UrlSource(urls, formats, client)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.db_session() as db:
            return corpus_service.sync_configured(db, config)["web"]

    def test_a_url_corpus_is_ingested_and_an_outage_keeps_what_was_indexed(self):
        state = {"status": 200}

        def handler(request):
            return httpx.Response(
                state["status"], headers={"content-type": "text/html"}, text=f"<p>{PENGUINS}</p>"
            )

        corpus = self.url_corpus(handler, refresh_minutes=30)
        info = self.corpus_info(corpus)
        self.assertEqual((info["source_type"], info["refresh_minutes"]), ("url", 30))

        self.assertEqual(self.ingest(corpus).json()["indexed"], ["example.com/guide.html"])

        state["status"] = 503
        body = self.ingest(corpus).json()
        self.assertEqual(body["failed"], {"example.com/guide.html": "The server answered 503."})
        [doc] = self.client.get(
            "/documents", params={"corpus_id": str(corpus.id)}, headers=self.as_admin()
        ).json()
        self.assertEqual(doc["status"], "ready")  # still searchable while the site is down
        self.assertIn("1 item(s)", self.corpus_info(corpus)["last_ingest_error"])
        self.assertIn("example.com/guide.html", self.hit_files(self.search(self.alice)))

    def test_a_url_that_never_worked_is_listed_as_failed(self):
        corpus = self.url_corpus(lambda request: httpx.Response(404))

        self.ingest(corpus)

        [doc] = self.client.get(
            "/documents", params={"corpus_id": str(corpus.id)}, headers=self.as_admin()
        ).json()
        self.assertEqual((doc["filename"], doc["status"]), ("example.com/guide.html", "failed"))
        self.assertEqual(doc["error"], "The server answered 404.")


if __name__ == "__main__":
    unittest.main()
