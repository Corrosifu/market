# Service `catalog`

**Rôle.** Catalogue marketplace : produits, offres, vendeurs. REST + GraphQL (Strawberry, DataLoader).

**Stockage.** MongoDB (JSON Schema par catégorie)

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
