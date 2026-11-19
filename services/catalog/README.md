# Service `catalog`

**Rôle.** Catalogue marketplace : produits, offres, vendeurs. REST et GraphQL (Strawberry, DataLoader).

**Stockage.** MongoDB, collections `products`, `offers`, `sellers`, chacune protégée par un validateur
`$jsonSchema` (`validationLevel: strict`, `validationAction: error`), réappliqué à chaque démarrage.

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka.
Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/catalog.json`.

## Routes

| Route | Rôle |
|---|---|
| `GET /v1/catalog/products?category=&first=` | Liste triée par identifiant. `first` dans [1, 50] (défaut 20), `category` = nom simple (`^[a-z][a-z0-9_]{0,63}$`). Hors bornes : 422. |
| `POST /v1/catalog/products` | Création réservée au rôle `seller` (`X-User-Role`), rattachée au vendeur `X-User-Id`. Autre rôle ou vendeur inconnu : 403 ; document refusé par le schéma de sa catégorie : 422. |
| `POST /v1/catalog/graphql` | `products(category, first)` : `id`, `title`, `category`, `description`, `sellerId`, `attributes`, `seller { id name }`. |
| `GET /healthz`, `GET /readyz` | Vivacité ; préparation avec sonde MongoDB (`ping`). |

`X-User-Role` et `X-User-Id` sont posés par NGINX après `auth_request` (valeurs du client écrasées). Le service leur
fait confiance **uniquement** parce qu'aucun de ses ports n'est publié hors du réseau compose.

Bornes (constantes de `market_catalog/settings.py`) : taille de page 50, GraphQL profondeur 5, 1000 jetons, 10 alias.
Le GraphQL n'accepte ni GET ni envoi de fichiers et n'expose pas d'IDE. Les champs d'introspection (`__schema`)
échappent à la limite de profondeur (choix de Strawberry) ; leur coût reste borné par la limite de jetons.

## Schémas par catégorie

Un fichier par catégorie : `schemas/<categorie>.json`, au sous-ensemble `$jsonSchema` de MongoDB (`bsonType`,
pas de `$schema`, `$id` ni `format`), attributs propres à la catégorie sous `properties.attributes.properties`.
Le validateur de `products` est un `$or` à une branche par fichier, `{category: <nom du fichier>, $jsonSchema: …}` :
un produit doit respecter le schéma de **sa** catégorie, et une catégorie sans fichier est refusée.
`electronics.json` et `books.json` sont livrés en S1 ; un fichier ajouté est pris en compte au redémarrage.

Compatibilité avec le jeu de démonstration (ADR 0001) : produits, vendeurs et offres acceptent un champ optionnel
`provenance_kind` (chaîne non vide), conservé tel quel ; la devise d'une offre est `GBP` (celle du jeu) ou `EUR`.

Aucune entrée n'est transmise telle quelle à MongoDB : les filtres sont construits à partir de valeurs typées
(`str`, `int`), les noms d'attributs en forme d'opérateur (`$…`) ou de chemin (`a.b`) sont refusés.

## Données de départ

Au démarrage, si `products` est vide **et** `ENVIRONMENT=local`, le service charge ses fixtures : le vendeur de
`seller@market.test` (identifiant `uuid5(NAMESPACE_URL, "market:seller@market.test")`, égal au `sub` émis par
`auth`), 12 produits (6 `electronics`, 6 `books`) et une offre par produit. Identifiants `uuid5` stables.

`python -m market_catalog.seed` les rétablit de façon idempotente (remplacement par identifiant, sans toucher aux
autres documents) ; refusé avec le code 2, sans rien écrire, si `ENVIRONMENT` n'est pas `local`.

## Lancement

Variables : `ENVIRONMENT` (défaut `local`), `MONGO_URL` (obligatoire, ex. `mongodb://mongo:27017/market` ; la base
est celle de l'URL, sinon `catalog`). `LOG_LEVEL` optionnel. Journaux JSON sur la sortie standard, uvicorn compris.

- Local, contre le MongoDB de la pile `core` (`make up`) :
  `MONGO_URL=mongodb://127.0.0.1:27017/catalog uv run uvicorn --factory market_catalog.main:create_app --port 8000`
- Image (contexte à la racine du dépôt) : `docker build -f services/catalog/Dockerfile .` ; `python:3.12.10-slim`,
  uv 0.13.8 (`pip install uv==0.13.8`), `uv sync --frozen --package market-catalog`, utilisateur non root
  (uid 10001, code en lecture seule), port 8000, healthcheck Python (`urllib`) sur `/healthz`, un seul worker.
  Le Dockerfile copie d'abord les seuls `pyproject.toml` du workspace (bibliothèque commune et tous les services,
  exigés par uv) et installe les dépendances : cette couche ne change qu'avec le verrou ou un `pyproject.toml`.
  Viennent ensuite le code de `market_common` (sans ses tests) et celui du catalogue. Aucun cache uv dans l'image
  (`UV_NO_CACHE=1`).
- Contrat : `uv run python -m market_catalog.openapi contracts/openapi/catalog.json` (un test vérifie qu'il est à jour).

## Tests

`uv run pytest services/catalog/tests`. Les tests d'intégration utilisent un vrai MongoDB : celui de
`CATALOG_TEST_MONGO_URL` s'il est défini (par exemple `mongodb://127.0.0.1:27017`, pile `core`), sinon un conteneur
`mongo:7.0.18` démarré une fois par session par testcontainers (environ 9 s, image déjà présente), puis arrêté.
Une base dédiée par test, supprimée ensuite. Docker absent : échec explicite, jamais un test sauté.
Le test sans N+1 compte les commandes `find` réellement reçues par MongoDB (`CommandListener` de pymongo).

## Limite assumée

MongoDB tourne **sans authentification** en S1, joignable sur le réseau compose et sur `127.0.0.1:27017` (port
publié pour les tests et les outils de l'hôte). Toute personne ayant accès à la machine peut lire et modifier le
catalogue. `MONGO_URL` est déjà traité comme un secret (`SecretStr`, jamais journalisé par le service) pour accueillir des identifiants quand
un compte dédié au catalogue sera créé.
