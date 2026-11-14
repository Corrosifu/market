"""Contrats de la pile locale, sans lire les secrets ni démarrer Docker."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ("auth", "orders", "inventory", "payment", "delivery", "realtime")


def services():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def test_images_match_version_reference():
    versions = dict(
        line.split("=", 1) for line in (ROOT / "infra/versions.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    for service, image in (("kafka", "apache/kafka"), ("postgres", "postgres"),
                           ("mongo", "mongo"), ("gateway", "nginx")):
        assert services()[service]["image"] == f"{image}:{versions[service.upper() + '_IMAGE_TAG']}"
    assert versions["SPARK_VERSION"] == versions["SPARK_KAFKA_CONNECTOR_VERSION"]


@pytest.mark.parametrize("additional_services", [
    {},
    {"auth": {"profiles": ["core"], "mem_limit": "256m", "ports": ["127.0.0.1:8001:8000"]}},
    {"spark": {"profiles": ["data"]}},
])
def test_core_is_bounded_and_local(additional_services):
    specs = {
        name: spec for name, spec in (services() | additional_services).items()
        if "core" in spec.get("profiles", [])
    }
    assert {"postgres", "mongo", "kafka", "gateway"} <= set(specs)
    for spec in specs.values():
        assert spec["mem_limit"]
        assert all(port.startswith("127.0.0.1:") for port in spec.get("ports", []))
    assert "-Xmx" in specs["kafka"]["environment"]["KAFKA_HEAP_OPTS"]
    assert "--wiredTigerCacheSizeGB" in specs["mongo"]["command"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_postgres_passwords_and_ownership(schema):
    spec = services()["postgres"]
    variable = f"{schema.upper()}_DB_PASSWORD"
    assert spec["environment"][variable] == "${" + variable + ":?}"
    script = (ROOT / "infra/postgres/init/01-schemas.sh").read_text(encoding="utf-8")
    assert f'{schema}_pw="${{{variable}:?}}"' in script
    assert f"CREATE ROLE {schema}_svc LOGIN PASSWORD :'{schema}_pw';" in script
    assert f"CREATE SCHEMA {schema} AUTHORIZATION {schema}_svc;" in script
    assert f"GRANT CONNECT ON DATABASE market TO {schema}_svc;" in script
    assert f"ALTER ROLE {schema}_svc IN DATABASE market SET search_path = {schema};" in script
    assert "REVOKE ALL ON SCHEMA public FROM PUBLIC;" in script
    assert "REVOKE ALL ON DATABASE market FROM PUBLIC;" in script


def test_kafka_listeners_support_container_and_host_clients():
    env = services()["kafka"]["environment"]
    assert env["KAFKA_ADVERTISED_LISTENERS"] == "PLAINTEXT://kafka:9092,EXTERNAL://localhost:29092"
    assert env["KAFKA_CONTROLLER_QUORUM_VOTERS"] == "1@kafka:9093"
    assert env["KAFKA_PROCESS_ROLES"] == "broker,controller"
    assert "localhost:9092" in " ".join(services()["kafka"]["healthcheck"]["test"])


def run_init(tmp_path, missing=None):
    # Double de psql : on observe les arguments et le SQL réellement émis par sh.
    psql = tmp_path / "psql"
    psql.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\ncat\n', encoding="utf-8")
    psql.chmod(0o755)
    env = {"PATH": f"{tmp_path}{os.pathsep}/usr/bin:/bin", "POSTGRES_USER": "postgres", "POSTGRES_DB": "market"}
    for schema in SCHEMAS:
        env[f"{schema.upper()}_DB_PASSWORD"] = "test-'-$literal;"
    if missing:
        env.pop(missing)
    return subprocess.run(
        ["sh", str(ROOT / "infra/postgres/init/01-schemas.sh")],
        env=env, capture_output=True, text=True, check=False,
    )


def test_init_preserves_special_characters_as_psql_arguments(tmp_path):
    result = run_init(tmp_path)
    assert result.returncode == 0, result.stderr
    for schema in SCHEMAS:
        assert f"{schema}_pw=test-'-$literal;\n" in result.stdout
        assert f"PASSWORD :'{schema}_pw'" in result.stdout
    assert result.stdout.count("test-'-$literal;") == len(SCHEMAS)
    assert "ON_ERROR_STOP=1" in result.stdout
    assert "BEGIN;" in result.stdout and "COMMIT;" in result.stdout


@pytest.mark.parametrize("schema", SCHEMAS)
def test_init_refuses_missing_password_before_calling_psql(tmp_path, schema):
    result = run_init(tmp_path, missing=f"{schema.upper()}_DB_PASSWORD")
    assert result.returncode != 0
    assert result.stdout == ""
