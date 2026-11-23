# Inventory

Réservation atomique du stock : une instruction `UPDATE … WHERE available >= :q RETURNING …`
par SKU, toutes les lignes et leurs mouvements dans une transaction. Les lignes dupliquées
sont additionnées et les SKU triés pour conserver le même ordre de verrouillage.
Les contraintes PostgreSQL refusent les compteurs négatifs.

Un verrou transactionnel par commande sérialise les réservations, confirmations et libérations
concurrentes de cette commande. Le rejeu d'une réservation renvoie son état courant sans
nouvel effet ; un autre ensemble de lignes répond 409. Une transition terminale rejouée
répond 204 ; la transition opposée répond 409. Une libération inconnue répond 204, une
confirmation inconnue 404. Une transaction en échec annule aussi les mouvements.

Routes :

- `GET /v1/inventory/{sku}` : `{sku, available, reserved}`, ou 404.
- `POST /v1/reservations` : `{order_id, lines: [{sku, quantity}]}`, réponse 201 avec
  `{order_id, status, lines}`, ou 409. Quantités entières strictes ≥ 1.
- `POST /v1/reservations/{order_id}/confirm` et `/release` : 204.
- `/healthz` : vivacité ; `/readyz` : accès à la table de stock (503 si indisponible).

Les routes de mutation sont internes, sans authentification : elles font confiance au
réseau Docker. Elles ne doivent pas être exposées par la passerelle : NGINX ne route que
`GET /v1/inventory/{sku}` (voir `gateway/nginx/default.conf`).

## Exécution

Depuis la racine : `docker build -f services/inventory/Dockerfile -t market-inventory:dev .`.
Lancer sur le réseau de la pile avec `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`INVENTORY_DB_PASSWORD` et `ENVIRONMENT`. Le rôle est `inventory_svc` ; aucun secret
par défaut ni lecture de fichier d'environnement. Dans la pile, le service est démarré par
`make up` (profil `core`) ; pour un essai isolé, lancer l'image sur le réseau compose du
projet avec la valeur d'`INVENTORY_DB_PASSWORD` de votre `.env`, et publier au plus
`127.0.0.1:18081:8000`.

L'image Python 3.12.10 démarre sous UID 10001, applique
`alembic -c services/inventory/alembic.ini upgrade head`, puis lance Uvicorn sur 8000.
Les migrations sont dans `alembic/versions/`, dans le schéma `inventory`.

`python -m market_inventory.seed` restaure les SKU `SKU-DEMO-1`, `SKU-DEMO-2` à 100 et
`SKU-LAST-1` à 1, avec `reserved=0`, et supprime leurs réservations. Cette opération
réinitialise volontairement ces fixtures : ne pas l'utiliser sur des commandes réelles.
Un verrou exclusif empêche le chevauchement avec les mutations de l'API ; les autres
SKU et l'historique des mouvements sont conservés. Le rejeu du seed est sans effet supplémentaire.

`on_hand` est la valeur d'ouverture chargée/initialisée ; les compteurs opérationnels
sont `available` et `reserved`. `RESERVE` et `RELEASE` décrivent la variation du disponible,
`CONFIRM` la sortie du réservé ; ne pas additionner ces trois types comme un solde physique.
Les identifiants sont TEXT. Les réservations sans commande et les types de mouvements
du paquet de démonstration sont acceptés ; `provenance_kind` reste nul pour l'API et les fixtures.

## Vérification

`.venv/bin/python -m pytest services/inventory/tests -q` utilise des doubles, sans Docker.
Le test d'insuffisance sur la seconde ligne vérifie le retour arrière complet et refuse
une implémentation qui lirait le stock avant de l'écrire. La concurrence réelle est vérifiée
avec PostgreSQL par un test sur la pile démarrée (dix commandes simultanées sur le
dernier article : une seule acceptée).
Le contrat versionné est généré par `market_inventory.main.create_app().openapi()`.
