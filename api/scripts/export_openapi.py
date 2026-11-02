"""Write the API's OpenAPI schema to docs/openapi.json.

    make openapi        (or: cd api && uv run python -m scripts.export_openapi)

The contract test compares the running app with this file, so a change to the API surface
fails the test until the file is regenerated and reviewed.
"""

import json
from pathlib import Path

from app.main import app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render(), encoding="utf-8")
    print(f"Wrote {OPENAPI_PATH}")


if __name__ == "__main__":  # pragma: no cover
    main()
