"""Export du contrat, sans démarrer le lifespan ni accéder à une dépendance."""

import json
from pathlib import Path

from market_order.main import app


def export(path: Path | None = None) -> None:
    if path is None:
        path = Path(__file__).resolve().parents[4] / "contracts/openapi/order.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    export()
