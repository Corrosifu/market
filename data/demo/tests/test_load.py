import subprocess

import pytest

from data.demo.dataset import CatalogData
from data.demo.errors import DatasetError
from data.demo.load import exclusive_import, import_documents, load_profile


def test_rejected_document_fails_import_and_never_publishes_staging():
    calls = []

    def run(args, input=None):
        calls.append((args, input))
        rejected = "mongoimport" in args and args[args.index("--collection") + 1].endswith("_products")
        return subprocess.CompletedProcess(args, 1 if rejected else 0, "",
            "0 document(s) imported successfully. 1 document(s) failed to import." if rejected else "")

    documents = {"sellers": [{"_id": "SELLER_SYN_a"}], "products": [{"_id": "PRD_a"}],
                 "offers": [{"_id": "OFFER_SYN_a"}]}
    with pytest.raises(DatasetError, match=r"products.*1 rejet"):
        import_documents(documents, run=run)
    scripts = [args[-1] for args, _ in calls if "mongosh" in args]
    assert not any("bulkWrite" in script for script in scripts)
    assert any(".drop()" in script for script in scripts)


def test_import_success_checks_actual_counts_and_reconciles_only_demo_prefixes():
    calls = []

    def run(args, input=None):
        calls.append((args, input))
        return subprocess.CompletedProcess(args, 0, '{"sellers":1,"products":1,"offers":1}', "")

    documents = {"sellers": [{"_id": "SELLER_SYN_a"}], "products": [{"_id": "PRD_a"}],
                 "offers": [{"_id": "OFFER_SYN_a"}]}
    assert import_documents(documents, run=run) == {"sellers": 1, "products": 1, "offers": 1}
    imports = [args for args, _ in calls if "mongoimport" in args]
    assert len(imports) == 3
    assert all("--stopOnError" in args and "--bypassDocumentValidation" not in args for args in imports)
    commit = next(args[-1] for args, _ in calls if "mongosh" in args and "bulkWrite" in args[-1])
    assert "validationAction" not in commit
    assert "deleteMany" in commit and '"PRD_"' in commit and "$nin" in commit


def test_catalog_is_rebuilt_before_any_import(monkeypatch, tmp_path):
    documents = {"sellers": [{"_id": "SELLER_SYN_a"}], "products": [{"_id": "PRD_a"}],
                 "offers": [{"_id": "OFFER_SYN_a"}]}
    selected = CatalogData(documents, ("order-a",), 1)
    monkeypatch.setattr("data.demo.load.read_catalog", lambda *args: selected)
    calls = []

    def run(args, input=None):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"sellers":1,"products":1,"offers":1}', "")

    load_profile(tmp_path, "ci", {"profiles": {"ci": selected.counts()}}, run=run)
    assert calls[0] == ["docker", "compose", "up", "-d", "--build", "--wait", "catalog"]


def test_manifest_mismatch_fails_before_database_changes(monkeypatch, tmp_path):
    selected = CatalogData({"sellers": [], "products": [], "offers": []}, (), 0)
    monkeypatch.setattr("data.demo.load.read_catalog", lambda *args: selected)
    calls = []
    with pytest.raises(DatasetError, match="manifeste"):
        load_profile(tmp_path, "ci", {"profiles": {"ci": {"products": 1}}}, run=calls.append)
    assert not calls


def test_concurrent_import_is_refused_and_the_lock_recovers_after_error(tmp_path):
    with pytest.raises(RuntimeError):
        with exclusive_import(tmp_path):
            with pytest.raises(DatasetError, match="déjà en cours"):
                with exclusive_import(tmp_path):
                    pytest.fail("Import concurrent admis")
            raise RuntimeError("interruption simulée")
    with exclusive_import(tmp_path):
        pass
