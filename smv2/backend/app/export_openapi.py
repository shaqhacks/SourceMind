"""Export the FastAPI OpenAPI schema to a JSON file.

Usage: python -m app.export_openapi [out_path]
Defaults to <smv2 repo root>/openapi.json. Importing app.main only builds the
FastAPI app object (no DB access happens until the ASGI lifespan runs), so
this works without a database present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.config import repo_root
from app.main import app


def export_openapi(out_path: Path) -> None:
    schema = app.openapi()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 else repo_root() / "openapi.json"
    export_openapi(out_path)
    print(f"wrote OpenAPI schema to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[:]))
