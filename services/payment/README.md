# Payment

Bouchon de capture : `POST /v1/payments`, corps `{order_id, amount, currency}` et en-tête
`Idempotency-Key` égal à `order_id` (422 sinon). Montant décimal fini strictement positif,
au plus deux décimales, compatible avec NUMERIC(12,2). Devise : trois lettres majuscules.
Réponse 201 : `{payment_id, status: "CAPTURED"}`.

`X-Simulate-Failure: payment` produit 402 `{status: "DECLINED"}` **uniquement** lorsque
`ENVIRONMENT=local`. L'en-tête est ignoré dans tout autre environnement. Le résultat
est persisté, y compris le refus : la même commande retrouve le premier résultat,
même si l'en-tête ou le corps changent. Il n'y a ni débit réel, ni remboursement en S2.

Une contrainte unique partielle protège les captures de l'API par commande ;
`INSERT … ON CONFLICT DO NOTHING RETURNING …`, puis lecture en cas de conflit, assure
l'idempotence même entre processus. Le paiement est validé en base avant la réponse.
Les captures et remboursements du paquet (`provenance_kind` non nul), leurs identifiants
TEXT et le statut `SUCCEEDED` sont compatibles avec la migration.

Le montant est conservé dans la colonne contractuelle `amount_gbp`, avec la devise reçue
dans une colonne `currency` supplémentaire (GBP par défaut pour le chargeur). Le bouchon
ne fait aucune conversion monétaire ; l'appelant S2 utilise GBP.

Cette route interne est sans authentification et fait confiance au réseau Docker.
Elle ne doit pas être exposée par NGINX, qui ne la route pas (voir `gateway/nginx/default.conf`).

## Exécution et vérification

Depuis la racine : `docker build -f services/payment/Dockerfile -t market-payment:dev .`.
Fournir `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `PAYMENT_DB_PASSWORD` et
`ENVIRONMENT` ; rôle `payment_svc`, aucun secret par défaut ni lecture de fichier d'environnement.
Dans la pile, le service est démarré par `make up` (profil `core`) ; pour un essai isolé,
lancer l'image sur le réseau compose du projet avec la valeur de `PAYMENT_DB_PASSWORD`
de votre `.env`, et publier au plus `127.0.0.1:18082:8000`.

L'image Python 3.12.10 démarre sous UID 10001, applique
`alembic -c services/payment/alembic.ini upgrade head`, puis lance Uvicorn sur 8000.
`GET /healthz` contrôle la vivacité ; `/readyz` contrôle l'accès à `payment.payments`.

`.venv/bin/python -m pytest services/payment/tests -q` utilise des doubles sans Docker.
Les essais PostgreSQL complètent ces tests pour les captures concurrentes et les contraintes.
Le contrat versionné est généré par `market_payment.main.create_app().openapi()`.
