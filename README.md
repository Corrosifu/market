# Market

Plateforme data e-commerce : une marketplace avec livraison (statuts d'expédition, répartition par hub, capacité des hubs), construite en microservices avec un lakehouse et un traitement temps réel.

Projet final d'équipe, Mastère Spécialisé Data et Generative AI Engineering (EFREI), rendu le 17 décembre 2026.

## État d'avancement

Livré (étapes S0 et S1) : pile locale (PostgreSQL avec un schéma et un rôle par service, MongoDB, Kafka, NGINX), service `auth` (JWT RS256 publié en JWKS, limitation des tentatives par e-mail), passerelle NGINX qui vérifie le jeton par `auth_request`, service `catalog` (MongoDB, JSON Schema par catégorie, REST et GraphQL avec DataLoader).

Livré (étape S2) : commandes, stock et paiement. Le service `order` crée une commande de façon idempotente (en-tête `Idempotency-Key`) et orchestre la Saga : réserver le stock, payer, confirmer ; en cas d'échec, compensation par opérations inverses (libération du stock), et une commande dont l'issue n'est pas établie reste `PENDING` jusqu'à sa reprise (sans délai maximal garanti tant que le paiement reste injoignable). Le service `inventory` réserve le stock par une instruction SQL conditionnelle, sous `CHECK (available >= 0)` : pas de survente, même en concurrence. Le service `payment` est un bouchon idempotent, avec échec simulable en local. Les appels sortants passent par `market_common.resilience` (délai, retry sur les seuls appels idempotents, circuit breaker, bulkhead). Les événements `OrderConfirmed` et `OrderCancelled` partent vers Kafka par une outbox écrite dans la même transaction que le statut ; livraison au moins une fois, les consommateurs dédupliquent par `event_id`. Le prix unitaire est encore fixe (**hypothèse** temporaire). Les autres services du dépôt (livraison, tableau de bord) sont des squelettes ; la liste ci-dessous décrit la cible.

## Objectifs de la plateforme

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
# clés JWT locales, ignorées par Git (une fois) :
mkdir -p infra/secrets
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out infra/secrets/jwt_private.pem
openssl pkey -in infra/secrets/jwt_private.pem -pubout -out infra/secrets/jwt_public.pem
make up                  # pile du profil core : bases, Kafka, auth, catalogue, commandes, stock, paiement, NGINX
make seed                # rétablit les comptes, produits et stocks de départ (pile démarrée)
make down
```

Profils Docker Compose : `core` (services et bases) aujourd'hui ; `data` (lakehouse), `stream` (Spark) et `obs` (Prometheus, Grafana, OpenTelemetry) arrivent avec les étapes suivantes, et `make up-demo` les démarrera.

## Données de démonstration

Un jeu de données de démonstration est publié à part, comme asset de la release `dataset-v3` de ce dépôt (43,8 Mo, SHA-256 `f7c08623b9987bcf8f017daf6d3b0a25bc5131dbc9db6c655854724afef205fc`) ; aucune donnée n'est versionnée. `make fetch-data` le télécharge et refuse toute archive dont l'empreinte diffère ; `make load-demo PROFILE=ci` (environ 300 commandes, leurs produits, offres et vendeurs) ou `PROFILE=demo` (paquet entier) charge le catalogue dans MongoDB, puis les commandes, lignes, paiements, stocks, réservations et mouvements dans PostgreSQL, pile démarrée ; `make up-demo` démarre la pile et charge le profil `demo`. Python 3.11 ou plus est requis sur le poste. Les commandes du jeu sont importées dans leur état final, sans passer par la Saga ni publier d'événement. Le chargement des livraisons arrive avec l'étape suivante (décision documentée dans `docs/adr/0001-jeu-de-donnees-de-demonstration.md`).

- **Source réelle** : *Online Retail II*, Daqing Chen (2012), UCI Machine Learning Repository, https://doi.org/10.24432/C5CG6D, sous licence CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Seuls sont réels les regroupements de factures, les noms de produits, les quantités, les prix unitaires et les dates d'origine (conservées dans les colonnes `*_at_source`) de 4 136 commandes d'un grossiste britannique d'articles cadeaux.
- **Adaptation** : le jeu est une version modifiée de cette source (factures de plus de 12 lignes exclues, identifiants clients pseudonymisés, dates décalées, données synthétiques ajoutées). Il n'est ni cautionné ni relu par l'auteur ou par l'UCI.
- **Le reste est synthétique ou dérivé par heuristique**, et marqué comme tel sur chaque ligne (`provenance_kind`) : vendeurs, offres, stock, paiements, hubs, colis, événements de livraison, 12 000 commandes supplémentaires, 15 des 26 catégories de produits ; les 11 autres catégories sont déduites des noms réels par des règles de mots-clés.
- Les identifiants des clients réels sont **pseudonymisés**, pas anonymes ; les courriels et adresses sont fictifs. Les dates sont décalées vers 2026, les dates d'origine étant conservées dans des colonnes `*_at_source` ; la devise est la livre sterling.
- Le chargement est séparé des données de départ (`make seed`) : relancé, il ne crée aucun doublon ; il est conçu pour ne pas modifier les comptes, produits et stocks de test : il ne remplace que les lignes marquées par `provenance_kind`, que les données de départ et les commandes passées par l'API n'ont pas.

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
make test        # tests qui ne demandent pas la pile démarrée (ceux du catalogue démarrent un MongoDB jetable : Docker requis)
```
