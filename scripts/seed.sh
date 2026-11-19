#!/bin/sh
set -eu

docker compose exec -T auth python -m market_auth.seed
docker compose exec -T catalog python -m market_catalog.seed
