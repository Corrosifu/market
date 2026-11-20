"""Import validé avant publication, puis réconciliation des seuls identifiants du jeu."""
import json
import os
import re
import subprocess
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from data.demo.dataset import PREFIXES, Document, read_catalog
from data.demo.errors import DatasetError

ROOT = Path(__file__).resolve().parents[2]
Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_command(args: list[str], input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, input=input, cwd=ROOT, capture_output=True, text=True,  # noqa: S603
                          encoding="utf-8", check=False, timeout=600)


def mongo_shell(script: str, run: Runner) -> str:
    result = run(["docker", "compose", "exec", "-T", "mongo", "mongosh", "--quiet", "--eval", script])
    if result.returncode:
        raise DatasetError(f"Commande MongoDB échouée : {result.stderr[-3000:]}")
    return result.stdout


SETUP = '''
for (const spec of specs) {
    const original = d.getCollectionInfos({name: spec.name})[0];
    if (!original || !original.options.validator || !Object.keys(original.options.validator).length) {
        throw new Error('Validateur absent pour ' + spec.name);
    }
    d.createCollection(spec.stage, {validator: original.options.validator,
        validationLevel: 'strict', validationAction: 'error'});
}
'''

PUBLISH = '''
(async () => {
// Vérifier toutes les préparations avant la première écriture dans les collections actives.
for (const spec of specs) {
    if (await d.getCollection(spec.stage).countDocuments({}) !== spec.count) {
        throw new Error(spec.name + ': nombre de documents préparés incorrect');
    }
    if (await d.getCollection(spec.stage).findOne({_id: {$not: new RegExp('^' + spec.prefix)}})) {
        throw new Error(spec.name + ': identifiant hors du jeu de démonstration');
    }
}
// Les parents précèdent les enfants pour préserver les références pendant la publication.
for (const spec of specs) {
    const target = d.getCollection(spec.name);
    let batch = [];
    for await (const doc of d.getCollection(spec.stage).find()) {
        batch.push({replaceOne: {filter: {_id: doc._id}, replacement: doc, upsert: true}});
        if (batch.length === 500) { await target.bulkWrite(batch, {ordered: true}); batch = []; }
    }
    if (batch.length) await target.bulkWrite(batch, {ordered: true});
}
// Retirer les anciens enfants avant leurs parents, sans toucher aux fixtures.
for (const spec of [...specs].reverse()) {
    const retained = await d.getCollection(spec.stage).distinct('_id');
    await d.getCollection(spec.name).deleteMany({_id: {$regex: '^' + spec.prefix, $nin: retained}});
}
const counts = {};
for (const spec of specs) {
    counts[spec.name] = await d.getCollection(spec.name).countDocuments({_id: new RegExp('^' + spec.prefix)});
}
print(JSON.stringify(counts));
})();
'''


def import_documents(documents: dict[str, list[Document]], *, run: Runner = run_command) -> dict[str, int]:
    token = uuid4().hex
    specs = [{"name": name, "stage": f"demo_import_{token}_{name}", "prefix": prefix, "count": len(documents[name])}
             for name, prefix in PREFIXES.items()]
    context = 'const d = db.getSiblingDB("market"); const specs = ' + json.dumps(specs) + ";\n"
    try:
        mongo_shell(context + SETUP, run)
        for spec in specs:
            name = str(spec["name"])
            content = "\n".join(json.dumps(row, ensure_ascii=False, allow_nan=False) for row in documents[name]) + "\n"
            result = run(["docker", "compose", "exec", "-T", "mongo", "mongoimport", "--db", "market",
                          "--collection", str(spec["stage"]), "--type", "json", "--mode", "insert", "--stopOnError"],
                         input=content)
            log = result.stdout + result.stderr
            failures = re.search(r"(\d+) document\(s\) failed to import", log)
            rejected = int(failures[1]) if failures else 0
            if result.returncode or rejected:
                raise DatasetError(f"{name} : {rejected} rejet(s), import refusé. {log[-2000:]}")
        output = mongo_shell(context + PUBLISH, run)
        counts = json.loads(output.strip().splitlines()[-1])
        expected = {name: len(rows) for name, rows in documents.items()}
        if counts != expected:
            raise DatasetError(f"Comptes MongoDB après import {counts}, attendus {expected}")
        return counts
    finally:
        mongo_shell(context + "for (const spec of specs) d.getCollection(spec.stage).drop();", run)


@contextmanager
def exclusive_import(cache: Path):
    """Empêcher deux commandes de ce checkout de publier des profils concurrents."""
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "import.lock").open("a+b") as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DatasetError("Un chargement est déjà en cours dans ce checkout") from exc
        yield  # Fermer le descripteur libère aussi le verrou en cas d'erreur.


def load_profile(package: Path, profile: str, manifest: dict[str, Any], *, run: Runner = run_command) -> dict[str, int]:
    data = read_catalog(package, profile)
    if data.counts() != manifest["profiles"][profile]:
        raise DatasetError(f"Comptes du profil {profile} différents du manifeste : {data.counts()}")
    with exclusive_import(ROOT / "data/demo/.cache"):
        print("Reconstruction du catalogue et application des validateurs…", flush=True)
        rebuilt = run(["docker", "compose", "up", "-d", "--build", "--wait", "catalog"])
        if rebuilt.returncode:
            raise DatasetError(f"Reconstruction du catalogue échouée : {(rebuilt.stdout + rebuilt.stderr)[-4000:]}")
        counts = import_documents(data.documents, run=run)
    print(f"Profil {profile} chargé : " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    return counts
