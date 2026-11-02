import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import export_openapi
from scripts.export_openapi import OPENAPI_PATH, render


class TestOpenApiSnapshot(unittest.TestCase):
    def test_schema_matches_the_committed_snapshot(self):
        self.assertTrue(OPENAPI_PATH.exists(), "Run `make openapi` to create docs/openapi.json.")
        committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        current = json.loads(render())
        self.assertEqual(
            current,
            committed,
            "The API changed. Review the change, then run `make openapi` to update the snapshot.",
        )

    def test_every_route_but_the_open_ones_requires_a_token(self):
        schema = json.loads(render())
        open_paths = {"/health", "/auth/login", "/auth/refresh"}
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                with self.subTest(route=f"{method.upper()} {path}"):
                    self.assertEqual(path in open_paths, "security" not in operation)

    def test_export_writes_the_schema_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "openapi.json"
            with mock.patch.object(export_openapi, "OPENAPI_PATH", target):
                export_openapi.main()
            self.assertEqual(target.read_text(encoding="utf-8"), render())
