"""Export du contrat OpenAPI : `python -m market_catalog.openapi contracts/openapi/catalog.json`.

Le document est produit par FastAPI sans connexion à MongoDB (le cycle de vie de l'application n'est pas lancé).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from market_catalog.main import create_app
from market_catalog.settings import CatalogSettings


def openapi_document() -> dict[str, Any]:
    app = create_app(CatalogSettings(mongo_url=SecretStr("mongodb://contract-export.invalid")))
    return app.openapi()


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage : python -m market_catalog.openapi <fichier.json>\n")
        return 2
    Path(argv[0]).write_text(render(openapi_document()), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
