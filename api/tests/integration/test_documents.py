"""Uploads, indexes with several embedding models and splitters, and per-user isolation."""

from tests.rag_helpers import PENGUINS, VOLCANOES, RagTestCase, pdf_bytes


class TestUpload(RagTestCase):
    def test_upload_indexes_with_the_defaults_and_records_how(self):
        response = self.upload(self.alice)

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["filename"], "penguins.txt")
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["owner_id"], str(self.alice.id))
        self.assertIsNone(body["corpus_id"])
        [index] = body["indexes"]
        self.assertEqual(
            {k: v for k, v in index.items() if k != "chunk_count"},
            {
                "embedding_name": "fake-a",
                "embedding_provider": "fake",
                "embedding_model": "fake-embed-a",
                "embedding_dimensions": 256,
                "chunking_name": "small",
                "chunking_method": "recursive",
                "chunk_size": 60,
                "chunk_overlap": 10,
            },
        )
        self.assertGreater(index["chunk_count"], 1)

    def test_every_chunk_carries_the_metadata_of_its_index(self):
        document = self.upload(self.alice, embedding="fake-b", chunking="para").json()

        chunks = self.client.get(
            f"/documents/{document['id']}/chunks", headers=self.as_user(self.alice)
        ).json()

        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertEqual(chunk["embedding_name"], "fake-b")
            self.assertEqual(chunk["embedding_model"], "fake-embed-b")
            self.assertEqual(chunk["embedding_dimensions"], 384)
            self.assertEqual(chunk["chunking_method"], "paragraph")
            self.assertEqual((chunk["chunk_size"], chunk["chunk_overlap"]), (200, 0))
            self.assertNotIn("embedding", chunk)  # the vector itself is not exposed

    def test_pdf_markdown_and_text_are_supported(self):
        for name, content in (
            ("a.pdf", pdf_bytes("Penguins live in Antarctica")),
            ("b.md", "# Notes\n\nPenguins."),
            ("c.txt", PENGUINS),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.upload(self.alice, name, content).status_code, 201)

    def test_bad_uploads_are_rejected_with_a_reason(self):
        cases = [
            (("a.docx", b"x"), {}, 422, "Unsupported file type"),
            (("a.txt", b"  "), {}, 422, "no text"),
            (("a.txt", PENGUINS), {"embedding": "nope"}, 422, "Unknown embedding model"),
            (("a.txt", PENGUINS), {"chunking": "nope"}, 422, "Unknown chunking strategy"),
            (("a.txt", PENGUINS), {"embedding": "offline"}, 503, "not available"),
        ]
        for (name, content), form, status, message in cases:
            with self.subTest(message=message):
                response = self.upload(self.alice, name, content, **form)

                self.assertEqual(response.status_code, status, response.text)
                self.assertIn(message, response.json()["detail"])
        self.assertEqual(self.documents(self.alice), [])  # nothing half-stored

    def test_an_embedding_failure_leaves_no_document_behind(self):
        def fail(*args, **kwargs):
            raise RuntimeError("provider exploded")

        self.provider.embed = fail

        response = self.upload(self.alice)

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("exploded", response.text)
        self.assertEqual(self.documents(self.alice), [])

    def test_oversized_files_are_refused(self):
        self.settings.app.limits.max_upload_mb = 1

        response = self.upload(self.alice, content="x" * (1024 * 1024 + 1))

        self.assertEqual(response.status_code, 413)

    def test_only_administrators_upload_into_a_corpus(self):
        corpus = self.create_corpus()

        denied = self.upload(self.alice, corpus_id=corpus["id"])
        missing = self.upload(self.admin, corpus_id="00000000-0000-0000-0000-000000000000")
        allowed = self.upload(self.admin, corpus_id=corpus["id"])

        self.assertEqual((denied.status_code, missing.status_code), (403, 404))
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.json()["corpus_id"], corpus["id"])
        self.assertIsNone(allowed.json()["owner_id"])

    def documents(self, user, **params):
        response = self.client.get("/documents", params=params, headers=self.as_user(user))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class TestSeveralIndexes(RagTestCase):
    def test_a_document_can_be_indexed_again_with_another_model_and_splitter(self):
        document = self.upload(self.alice).json()

        response = self.client.post(
            f"/documents/{document['id']}/index",
            json={"embedding": "fake-b", "chunking": "para"},
            headers=self.as_user(self.alice),
        )

        self.assertEqual(response.status_code, 200, response.text)
        pairs = {(i["embedding_name"], i["chunking_name"]) for i in response.json()["indexes"]}
        self.assertEqual(pairs, {("fake-a", "small"), ("fake-b", "para")})

    def test_a_failed_reindex_keeps_the_existing_indexes(self):
        document = self.upload(self.alice).json()
        self.provider.embed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))

        response = self.client.post(
            f"/documents/{document['id']}/index",
            json={"embedding": "fake-b"},
            headers=self.as_user(self.alice),
        )

        self.assertEqual(response.status_code, 502)
        after = self.client.get(f"/documents/{document['id']}", headers=self.as_user(self.alice))
        self.assertEqual([i["embedding_name"] for i in after.json()["indexes"]], ["fake-a"])

    def test_indexing_the_same_way_again_replaces_instead_of_duplicating(self):
        document = self.upload(self.alice).json()
        before = document["indexes"][0]["chunk_count"]

        again = self.client.post(
            f"/documents/{document['id']}/index", json={}, headers=self.as_user(self.alice)
        ).json()

        self.assertEqual([i["chunk_count"] for i in again["indexes"]], [before])

    def test_search_only_uses_the_chosen_index(self):
        self.upload(self.alice, "a.txt", PENGUINS)  # fake-a / small
        self.upload(self.alice, "b.txt", PENGUINS, embedding="fake-b")  # fake-b / small
        self.upload(self.alice, "c.txt", PENGUINS, chunking="para")  # fake-a / para

        default = self.search(self.alice)
        other_model = self.search(self.alice, embedding="fake-b")
        other_splitter = self.search(self.alice, chunking="para")

        self.assertEqual(set(self.hit_files(default)), {"a.txt"})
        self.assertEqual(set(self.hit_files(other_model)), {"b.txt"})
        self.assertEqual(set(self.hit_files(other_splitter)), {"c.txt"})
        self.assertEqual(default.json()["embedding_name"], "fake-a")
        self.assertEqual(other_splitter.json()["chunking_name"], "para")

    def test_changing_the_configuration_leaves_old_chunks_unmatched_until_reindexed(self):
        document = self.upload(self.alice).json()
        self.settings.rag.chunking_strategies["small"].size = 70  # same name, new parameters

        self.assertEqual(self.hit_files(self.search(self.alice)), [])

        self.client.post(
            f"/documents/{document['id']}/index", json={}, headers=self.as_user(self.alice)
        )
        self.assertEqual(set(self.hit_files(self.search(self.alice))), {"penguins.txt"})
        sizes = {i["chunk_size"] for i in self.documents_of(self.alice)[0]["indexes"]}
        self.assertEqual(sizes, {60, 70})  # both indexes are recorded

    def documents_of(self, user):
        return self.client.get("/documents", headers=self.as_user(user)).json()


class TestIsolation(RagTestCase):
    def test_users_only_see_their_own_documents(self):
        mine = self.upload(self.alice, "alice.txt", PENGUINS).json()
        self.upload(self.bob, "bob.txt", VOLCANOES)

        alice_list = self.client.get("/documents", headers=self.as_user(self.alice)).json()

        self.assertEqual([d["filename"] for d in alice_list], ["alice.txt"])
        for path in ("", "/chunks"):
            response = self.client.get(
                f"/documents/{mine['id']}{path}", headers=self.as_user(self.bob)
            )
            self.assertEqual(response.status_code, 404, path)

    def test_other_users_cannot_change_or_delete_a_document(self):
        mine = self.upload(self.alice).json()

        reindex = self.client.post(
            f"/documents/{mine['id']}/index", json={}, headers=self.as_user(self.bob)
        )
        delete = self.client.delete(f"/documents/{mine['id']}", headers=self.as_user(self.bob))
        admin_delete = self.client.delete(
            f"/documents/{mine['id']}", headers=self.as_user(self.admin)
        )

        self.assertEqual((reindex.status_code, delete.status_code), (404, 404))
        self.assertEqual(admin_delete.status_code, 404)  # admins manage corpora, not private files
        self.assertEqual(
            len(self.client.get("/documents", headers=self.as_user(self.alice)).json()), 1
        )

    def test_one_users_documents_never_appear_in_another_users_search(self):
        self.upload(self.alice, "alice.txt", PENGUINS)
        self.upload(self.bob, "bob.txt", VOLCANOES)

        self.assertEqual(
            set(self.hit_files(self.search(self.bob, "penguins Antarctica fish"))), set(["bob.txt"])
        )
        self.assertEqual(
            set(self.hit_files(self.search(self.alice, "penguins Antarctica fish"))),
            set(["alice.txt"]),
        )
        self.assertEqual(self.hit_files(self.search(self.admin, "penguins")), [])

    def test_delete_removes_the_document_and_its_chunks(self):
        document = self.upload(self.alice).json()

        response = self.client.delete(
            f"/documents/{document['id']}", headers=self.as_user(self.alice)
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.hit_files(self.search(self.alice)), [])
        self.assertEqual(
            self.client.get(
                f"/documents/{document['id']}", headers=self.as_user(self.alice)
            ).status_code,
            404,
        )


class TestOptionsAndSearch(RagTestCase):
    def test_options_list_models_splitters_and_availability(self):
        body = self.client.get("/rag/options", headers=self.as_user(self.alice)).json()

        models = {m["name"]: m for m in body["embedding_models"]}
        self.assertEqual(set(models), {"fake-a", "fake-b", "offline"})
        self.assertTrue(models["fake-a"]["available"])
        self.assertFalse(models["offline"]["available"])  # its provider is not running
        self.assertEqual(models["fake-b"]["dimensions"], 384)
        self.assertEqual(
            {c["name"]: c["method"] for c in body["chunking_strategies"]},
            {"small": "recursive", "para": "paragraph"},
        )
        self.assertEqual((body["default_embedding"], body["default_chunking"]), ("fake-a", "small"))
        self.assertEqual(body["supported_formats"], ["pdf", "txt", "md"])

    def test_search_returns_scored_passages_and_honours_top_k_and_min_score(self):
        self.upload(self.alice, "a.txt", PENGUINS + "\n\n" + VOLCANOES)

        top = self.search(self.alice, top_k=1).json()["hits"]
        self.settings.rag.retrieval.min_score = 0.99
        strict = self.search(self.alice, "unrelated words entirely")

        self.assertEqual(len(top), 1)
        self.assertIn("enguins", top[0]["text"])
        self.assertGreater(top[0]["score"], 0.2)
        self.assertEqual((top[0]["embedding_name"], top[0]["chunking_name"]), ("fake-a", "small"))
        self.assertEqual(self.hit_files(strict), [])

    def test_search_validates_input(self):
        for body in ({"query": ""}, {"query": "x", "top_k": 0}, {"query": "x", "extra": 1}):
            with self.subTest(body=body):
                response = self.client.post(
                    "/rag/search", json=body, headers=self.as_user(self.alice)
                )
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.search(self.alice, embedding="nope").status_code, 422)


if __name__ == "__main__":
    import unittest

    unittest.main()
