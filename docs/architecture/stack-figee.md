# Stack figée (synthèse)

Ce fichier résume les choix retenus ; les alternatives étudiées et leurs conséquences sont détaillées dans les ADR (`docs/adr/`).

| Domaine | Choix | Plan B |
|---|---|---|
| Langage | Python 3.12 (backend, données) ; TypeScript pour l'interface seulement | — |
| API | FastAPI, Strawberry (GraphQL, DataLoader) | — |
| Transactionnel | PostgreSQL, un schéma et un rôle par service, SQLAlchemy 2 async, Alembic | — |
| NoSQL | MongoDB, JSON Schema par catégorie | — |
| Lakehouse | MinIO + Delta Lake + Hive Metastore, quatre zones | SeaweedFS ou Garage |
| Bus | Kafka KRaft, un broker | — |
| Streaming | Spark Structured Streaming (`foreachBatch`, upsert idempotent) | — |
| Gateway | NGINX avec `auth_request` | Traefik |
| Authentification | service auth, JWT RS256, JWKS | Keycloak |
| Résilience | `libs/market_common` : httpx, tenacity, breaker, bulkhead | — |
| Saga | orchestrée par `order`, outbox avec relais, `Idempotency-Key`, `processed_events` | Debezium (écarté : mémoire) |
| Observabilité | OpenTelemetry, Prometheus, Grafana ; Jaeger optionnel | — |
| Qualité des données | règles PySpark, Delta CHECK, quarantaine, Hive Metastore + dictionnaire généré | OpenMetadata (écarté : mémoire) |
| Interface | React (Vite, TypeScript) + `dashboard-api` | Streamlit sur la même API |
| Déploiement et CI | Docker Compose à profils, uv, GitHub Actions, SonarQube Cloud | profil `quality` en local |

## Points à valider ou susceptibles de changer
- Seuil de saturation 85 %, fenêtre 5 minutes, watermark 10 minutes : hypothèses.
- Limite de lignes de l'offre gratuite de SonarQube Cloud : à revérifier.
- Versions épinglées ensemble dans `infra/versions.env` (S0) : Python 3.12, Java 17, Spark 3.5.5, Delta 3.3.2, connecteurs Kafka et S3, images. MinIO est figé sur la dernière release publiée (`RELEASE.2025-10-15T17-29-55Z`) ; la disponibilité de l'image reste à vérifier avant S5 (plan B : SeaweedFS ou Garage).
- Choix `fetch-event-source` ou cookie HttpOnly pour le flux temps réel : en S6.
- Qui porte l'interface : à décider dans l'équipe.
