.PHONY: help test lint up up-demo seed down fetch-data load-demo

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

PROFILE ?= ci

up-demo:  ## Pile complète (profils à venir) et jeu de démonstration complet
	docker compose --profile core --profile data --profile stream --profile obs up -d --wait
	python3 -m data.demo up-demo

fetch-data:  ## Télécharge le jeu de démonstration et vérifie son empreinte SHA-256
	python3 -m data.demo fetch

load-demo:  ## Charge le jeu de démonstration (catalogue, commandes, stock) : PROFILE=ci ou demo (pile démarrée)
	python3 -m data.demo load --profile "$(PROFILE)"

down:  ## Arrête la pile
	docker compose --profile core --profile data --profile stream --profile obs down
