# Service `inventory`

**Rôle.** Stock : réservations et libérations atomiques, contrainte CHECK stock >= 0.

**Stockage.** PostgreSQL schéma `inventory`

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
