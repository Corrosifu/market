# Service `payment`

**Rôle.** Paiement : bouchon (stub) avec échecs simulables pour démontrer la compensation.

**Stockage.** PostgreSQL schéma `payment`

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
