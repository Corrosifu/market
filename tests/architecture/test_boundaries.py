"""Frontières exécutables : le domaine ne dépend pas de l'infrastructure, les services ne s'importent pas entre eux,
la bibliothèque commune ne contient aucune règle métier. Analyse statique (AST), sans démarrer quoi que ce soit."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("auth", "catalog", "order", "inventory", "payment", "delivery", "dashboard_api")
INFRA_MODULES = {"fastapi", "starlette", "sqlalchemy", "asyncpg", "alembic", "pymongo", "motor", "confluent_kafka",
                 "aiokafka", "httpx", "strawberry", "pyspark", "boto3"}


def imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def violations(root: Path) -> list[str]:
    out: list[str] = []
    for service in SERVICES:
        pkg = f"market_{service}"
        base = root / "services" / service / "src" / pkg
        if not base.exists():
            continue
        other = {f"market_{s}" for s in SERVICES} - {pkg}
        for path in base.rglob("*.py"):
            mods = imports_of(path)
            rel = path.relative_to(root).as_posix()
            if mods & other:
                out.append(f"{rel}: import d'un autre service {sorted(mods & other)}")
            if "domain" in path.relative_to(base).parts and mods & INFRA_MODULES:
                out.append(f"{rel}: le domaine importe de l'infrastructure {sorted(mods & INFRA_MODULES)}")
    common = root / "libs" / "market_common" / "market_common"
    if common.exists():
        services_pkgs = {f"market_{s}" for s in SERVICES}
        for path in common.rglob("*.py"):
            if imports_of(path) & services_pkgs:
                out.append(f"{path.relative_to(root).as_posix()}: la bibliothèque commune importe un service")
    return out


def test_repository_respects_boundaries():
    assert violations(ROOT) == []


def _write(root: Path, rel: str, code: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")


def test_detects_domain_importing_infrastructure(tmp_path):
    _write(tmp_path, "services/order/src/market_order/domain/saga.py", "from sqlalchemy import select\n")
    assert any("domaine" in v for v in violations(tmp_path))


def test_detects_service_importing_another_service(tmp_path):
    _write(tmp_path, "services/order/src/market_order/api/routes.py", "import market_inventory.models\n")
    assert any("autre service" in v for v in violations(tmp_path))


def test_detects_common_library_importing_a_service(tmp_path):
    _write(tmp_path, "libs/market_common/market_common/x.py", "from market_order import saga\n")
    assert any("bibliothèque commune" in v for v in violations(tmp_path))


def test_accepts_clean_layout(tmp_path):
    _write(tmp_path, "services/order/src/market_order/domain/saga.py", "import dataclasses\n")
    _write(tmp_path, "services/order/src/market_order/api/routes.py", "from fastapi import APIRouter\nimport market_common\n")
    assert violations(tmp_path) == []
