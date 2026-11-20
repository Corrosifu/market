import hashlib
import io
import zipfile

import pytest

from data.demo.fetch import IntegrityError, prepared_dataset


def archive_bytes(name="verify.py"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, "print('verified')\n")
    return buffer.getvalue()


def test_wrong_checksum_prevents_extraction_and_execution(tmp_path):
    verified = []
    payload = archive_bytes()
    manifest = {"url": "https://example.invalid/data.zip", "sha256": "0" * 64}

    def download(url, path):
        path.write_bytes(payload)

    with pytest.raises(IntegrityError, match="SHA-256"):
        with prepared_dataset(manifest, tmp_path, download=download, verify=verified.append):
            pytest.fail("Le paquet invalide ne doit pas être préparé")
    assert not verified
    assert not list(tmp_path.rglob("verify.py"))


def test_valid_cached_zip_is_reused_without_network_and_extraction_is_fresh(tmp_path):
    payload = archive_bytes()
    manifest = {"url": "https://example.invalid/data.zip", "sha256": hashlib.sha256(payload).hexdigest()}
    calls, verified = [], []

    def download(url, path):
        calls.append(url)
        path.write_bytes(payload)

    for _ in range(2):
        with prepared_dataset(manifest, tmp_path, download=download, verify=verified.append) as root:
            assert (root / "verify.py").read_text(encoding="utf-8") == "print('verified')\n"
            (root / "verify.py").write_text("modified cache", encoding="utf-8")
        assert not root.exists()
    assert calls == [manifest["url"]]
    assert len(verified) == 2


def test_archive_paths_cannot_escape_the_cache(tmp_path):
    payload = archive_bytes("../escaped.py")
    manifest = {"url": "https://example.invalid/data.zip", "sha256": hashlib.sha256(payload).hexdigest()}

    def download(url, path):
        path.write_bytes(payload)

    with pytest.raises(IntegrityError, match="chemin"):
        with prepared_dataset(manifest, tmp_path, download=download, verify=lambda root: None):
            pytest.fail("Chemin sortant du cache")
    assert not (tmp_path.parent / "escaped.py").exists()


def test_windows_checksum_paths_are_portable_without_changing_hashes_or_scripts(tmp_path):
    buffer = io.BytesIO()
    script = b"print('original verifier')\n"
    data = b"original data\n"
    digest = hashlib.sha256(data).hexdigest()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("verify.py", script)
        archive.writestr("tables/data.csv", data)
        archive.writestr("SHA256SUMS", digest + "  tables\\data.csv\n")
    payload = buffer.getvalue()
    manifest = {"url": "https://example.invalid/data.zip", "sha256": hashlib.sha256(payload).hexdigest()}

    def download(url, path):
        path.write_bytes(payload)

    def verify(root):
        line = (root / "SHA256SUMS").read_text(encoding="utf-8").strip()
        expected, filename = line.split("  ", 1)
        assert expected == digest
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == expected
        assert (root / "verify.py").read_bytes() == script
        assert (root / "tables/data.csv").read_bytes() == data

    with prepared_dataset(manifest, tmp_path, download=download, verify=verify):
        assert (tmp_path / "Market_English_v3.zip").read_bytes() == payload
