"""Archive épinglée et extraction éphémère vérifiée avant toute exécution."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from data.demo.errors import DatasetError

ARCHIVE_NAME = "Market_English_v3.zip"


class IntegrityError(DatasetError):
    pass


class DownloadUnavailable(DatasetError):
    pass


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_archive(url: str, destination: Path) -> None:
    if not url.startswith("https://"):
        raise IntegrityError("Le téléchargement du paquet exige HTTPS")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as target:  # noqa: S310
            shutil.copyfileobj(response, target)
    except (urllib.error.URLError, OSError) as exc:
        raise DownloadUnavailable(f"Téléchargement indisponible : {exc}") from exc


def verify_package(root: Path) -> None:
    result = subprocess.run(  # noqa: S603 -- Script de l'archive dont le SHA-256 vient d'être contrôlé.
        [sys.executable, "-B", str(root / "verify.py")], cwd=root,
        capture_output=True, text=True, encoding="utf-8", check=False, timeout=300,
    )
    if result.returncode:
        raise IntegrityError(f"Vérification du paquet échouée : {result.stderr[-2000:]}")
    report = json.loads(result.stdout)
    if report.get("passed") is not True or "all_file_sha256_checksums" not in report.get("checks_passed", []):
        raise IntegrityError("Le vérificateur du paquet n'a pas confirmé sa validité")
    print(f"Paquet vérifié : {report['products']} produits, {report['category_count']} catégories")


def native_checksum_paths(root: Path) -> None:
    """Adapter l'index de chemins à l'OS, sans modifier les empreintes ni les fichiers vérifiés."""
    index = root / "SHA256SUMS"
    if not index.exists():
        return
    lines = []
    for line in index.read_text(encoding="utf-8").splitlines():
        digest, filename = line.split("  ", 1)
        relative = PurePosixPath(filename.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or ":" in filename:
            raise IntegrityError(f"Index SHA256SUMS : chemin interdit {filename!r}")
        lines.append(digest + "  " + str(Path(*relative.parts)))
    # SHA256SUMS exclut sa propre empreinte dans le paquet v3.
    # Le vérificateur original contrôlera les mêmes 63 fichiers et la couverture complète.
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")


@contextmanager
def prepared_dataset(
    manifest: Mapping[str, object], cache: Path, *,
    download: Callable[[str, Path], None] = download_archive,
    verify: Callable[[Path], None] = verify_package,
) -> Iterator[Path]:
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ARCHIVE_NAME
    expected = str(manifest["sha256"])
    if not archive.exists():
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".download", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            download(str(manifest["url"]), temporary)
            if checksum(temporary) != expected:
                raise IntegrityError("SHA-256 du téléchargement différent du manifeste : aucune extraction")
            os.replace(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)
    # Recontrôler le cache à chaque utilisation, avant extraction et exécution.
    if checksum(archive) != expected:
        raise IntegrityError("SHA-256 du ZIP en cache différent du manifeste : aucune extraction")
    with tempfile.TemporaryDirectory(prefix="dataset-v3-", dir=cache) as directory:
        root = Path(directory).resolve()
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                    raise IntegrityError(f"Archive : chemin interdit {entry.filename!r}")
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise IntegrityError(f"Archive : lien interdit dans le chemin {entry.filename!r}")
            package.extractall(root)  # noqa: S202 -- Tous les chemins et types sont contrôlés avant extraction.
        native_checksum_paths(root)
        verify(root)
        yield root
