.PHONY: help test lint up up-demo seed down

help:  ## Affiche les commandes
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/ :/'

test:  ## Tous les tests hors pile démarrée
	uv run --frozen pytest -m "not live"

lint:  ## ruff
	uv run --frozen ruff check .

up:  ## Pile minimale (profil core)
	docker compose --profile core up -d

seed:  ## Rétablit les comptes et produits de départ (pile démarrée)
	sh scripts/seed.sh

up-demo:  ## Pile complète (profils à venir)
	docker compose --profile core --profile data --profile stream --profile obs up -d

down:  ## Arrête la pile
	docker compose --profile core --profile data --profile stream --profile obs down
