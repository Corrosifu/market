# Service `delivery`

**Rôle.** Livraison (extension marketplace) : hubs, capacité, expéditions, statuts, affectation atomique de hub.

**Stockage.** PostgreSQL schéma `delivery` (partitionnement mensuel de shipment_events)

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
