# Service `auth`

**Rôle.** Authentification : émet les JWT RS256 et publie la clé publique (JWKS). Appelé par NGINX via auth_request.

**Stockage.** PostgreSQL schéma `auth`

**Règles.** Ce service ne lit jamais la base d'un autre service ; il communique par REST, GraphQL ou Kafka. Contrat OpenAPI généré par FastAPI, exporté dans `contracts/openapi/`.

**État.** À implémenter.
