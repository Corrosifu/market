# Service `dashboard_api`

**Rôle.** API en lecture seule pour l'interface : PostgreSQL `realtime` + tables consumption Delta, flux SSE.

**Stockage.** Lecture : PostgreSQL schéma `realtime`, Delta Lake (consumption)

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
