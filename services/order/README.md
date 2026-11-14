# Service `order`

**Rôle.** Commandes : orchestre la Saga (stock, paiement, livraison), outbox, clés d'idempotence.

**Stockage.** PostgreSQL schéma `orders` (partitionnement mensuel)

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
