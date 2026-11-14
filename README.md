# Market

Plateforme data e-commerce : une marketplace avec livraison (statuts d'expédition, répartition par hub, capacité des hubs), construite en microservices avec un lakehouse et un traitement temps réel.

Projet final d'équipe, Mastère Spécialisé Data et Generative AI Engineering (EFREI), rendu le 17 décembre 2026.

## Ce que fait la plateforme

- **Commandes** : création idempotente (en-tête `Idempotency-Key`), Saga orchestrée avec compensation (paiement refusé : la commande est annulée et le stock libéré).
- **Stock** : réservations dans PostgreSQL, contrainte `CHECK (stock >= 0)` : pas de survente, même en concurrence.
- **Catalogue** : MongoDB, un JSON Schema par catégorie de produit ; API REST (OpenAPI) et GraphQL.
- **Livraison** : une expédition par vendeur et par commande, statuts contrôlés (transition invalide : 409), affectation d'un hub atomique en SQL.
- **Temps réel** : Kafka et Spark Structured Streaming (fenêtres, watermark, checkpoint) pour détecter la saturation d'un hub et les retards d'expédition.
- **Lakehouse** : MinIO (S3) et Delta Lake, zones raw, staging, curated et consumption, contrôles de qualité, pseudonymisation dès la zone staging.
- **Observabilité** : OpenTelemetry, Prometheus, Grafana.

## Architecture

```
Navigateur ──► NGINX (gateway, auth_request) ──► auth · catalog · order · inventory · payment · delivery · dashboard-api
                                                       │            │
                                          PostgreSQL (un schéma    MongoDB
                                          et un rôle par service)  (catalogue)
                                                       │
                                  outbox ──► Kafka ──► Spark Structured Streaming ──► Delta (MinIO) ──► dashboard-api ──► interface
```

Le détail des choix techniques et des limites assumées se trouve dans `docs/architecture/`. Les décisions d'architecture sont dans `docs/adr/`.

## Démarrer

Prérequis : Docker et Docker Compose, Python 3.12, uv, Make.

```bash
cp .env.example .env     # puis adapter localement ; le vrai .env n'est jamais versionné
make up                  # pile minimale (profil core)
make up-demo             # pile complète : core, data, stream, obs
make down
```

Profils Docker Compose : `core` (services et bases), `data` (lakehouse), `stream` (Kafka et Spark), `obs` (Prometheus, Grafana, OpenTelemetry).

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `contracts/` | contrats écrits d'abord : OpenAPI et schémas d'événements |
| `services/` | un dossier par microservice : `auth`, `catalog`, `order`, `inventory`, `payment`, `delivery`, `dashboard_api` |
| `libs/market_common/` | code partagé : résilience (timeout, retry, circuit breaker, bulkhead), journaux, traces |
| `data/` | jobs Spark (streaming et batch), contrôles de qualité, lakehouse |
| `simulator/` | simulateur de transporteurs |
| `gateway/` | configuration NGINX |
| `infra/` | Docker Compose, initialisation PostgreSQL, Prometheus, Grafana, OpenTelemetry |
| `frontend/` | interface React (TypeScript) |
| `tests/` | tests d'intégration et de charge |
| `docs/` | architecture, ADR, notes de démonstration |
| `docker-compose.yml`, `.env.example` | démarrage en une commande ; variables à remplir |

## Qualité et sécurité

- Aucun secret dans le dépôt : seules des valeurs factices dans `.env.example`, contrôle `gitleaks` en CI.
- Intégration continue à chaque commit : lint (`ruff`), tests, recherche de secrets.
- Authentification JWT (RS256, clés publiées en JWKS) vérifiée par la gateway.
- Les données personnelles sont **pseudonymisées**, pas anonymisées : le lien avec la personne reste possible avec la clé.

## Hypothèses à valider

Ces valeurs sont lues de la configuration et restent des hypothèses de travail : seuil de saturation d'un hub à 85 %, fenêtre d'agrégation de 5 minutes, watermark de 10 minutes.

## Tests

```bash
make lint
make test        # tests qui ne demandent pas la pile démarrée
```
