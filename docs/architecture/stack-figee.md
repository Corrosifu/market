# Stack figée (synthèse)

Source détaillée : document « Market : justification des choix techniques » (alternatives, avantages, inconvénients, questions de jury). Ce fichier n'en garde que les décisions.

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
- Version exacte de MinIO à figer.
- Choix `fetch-event-source` ou cookie HttpOnly pour le flux temps réel : en S6.
- Qui porte l'interface : à décider dans l'équipe.
