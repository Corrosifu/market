"""Commandes du jeu v3. Les données restent dans le cache local et dans MongoDB."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from data.demo.errors import DatasetError
from data.demo.fetch import DownloadUnavailable, prepared_dataset
from data.demo.load import load_profile
from data.demo.schemas import write_schemas

DIRECTORY = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Jeu de démonstration Market v3")
    parser.add_argument("action", choices=["fetch", "load", "up-demo", "schemas"])
    parser.add_argument("--profile", choices=["ci", "demo"], default="ci")
    args = parser.parse_args()
    try:
        manifest = json.loads((DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
        with prepared_dataset(manifest, DIRECTORY / ".cache") as package:
            if args.action in {"load", "up-demo"}:
                load_profile(package, "demo" if args.action == "up-demo" else args.profile, manifest)
            elif args.action == "schemas":
                write_schemas(package, DIRECTORY.parents[1] / "services/catalog/schemas")
    except DownloadUnavailable as exc:
        if args.action == "up-demo":
            print(f"{exc}. Paquet indisponible, la pile continue avec les fixtures locales.", file=sys.stderr)
            return 0
        print(str(exc), file=sys.stderr)
        return 1
    except (DatasetError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
