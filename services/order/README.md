# Order

Service de commandes : `POST /v1/orders` prend `{lines: [{sku, quantity}]}` et une
`Idempotency-Key`, `GET /v1/orders/{id}` renvoie l'état courant. Quantités entières
strictement positives et liste non vide. L'identité vient de `X-User-Id` (401 absent) ;
une commande d'un autre client répond 404, sauf `X-User-Role: ops`.
Ces en-têtes doivent être écrasés par la passerelle : le service interne fait confiance
au réseau Docker et ne vérifie pas lui-même de JWT.

## Saga et reprise

Une commande suit réserver → payer → confirmer. Chaque étape est persistée dans une
transaction courte ; aucune connexion de base n'est conservée pendant un appel HTTP.
La clé d'idempotence « en cours » est commitée avant ces appels : son rejeu répond 409.
Une autre empreinte de corps répond 422 ; la même clé d'un autre client est indépendante.

Le paiement refusé entraîne release puis CANCELLED (201). Si toutes les tentatives ont
échoué avant envoi (ConnectError, DNS compris, circuit ouvert ou bulkhead plein), release
puis CANCELLED répond 503. Une tentative qui a pu atteindre payment (délai, coupure après
envoi, 5xx) conserve PENDING avec 503, même si une tentative ultérieure échoue à se connecter.
Une confirmation ou libération non terminée conserve également PENDING.

Après capture, aucun chemin ne libère le stock.
Un `confirm` recevant 404 (réservation inconnue, par exemple après `make seed`) ou 409
laisse la commande `PENDING`, avec un avertissement périodique à chaque reprise,
puisque le stock n'est jamais libéré après capture.
Une issue de paiement inconnue est
résolue par un rappel avec la même clé : CAPTURED entraîne confirm puis CONFIRMED,
DECLINED entraîne release puis CANCELLED. Si payment reste injoignable, le stock reste
réservé et la saga PENDING ; il n'y a **aucun délai maximal garanti** ni remboursement
en S2. Chaque maintien en attente produit un journal d'avertissement.

La reprise tourne dès le démarrage puis périodiquement sur les sagas immobiles depuis
`SAGA_STUCK_SECONDS`. Une réservation au résultat inconnu, sans début de paiement, est
libérée ; une compensation inachevée est rejouée. Les requêtes actives sont exclues de
la reprise ; les autres sagas sont prises par `FOR UPDATE SKIP LOCKED`, avec un propriétaire
vérifié à chaque checkpoint. Le déploiement S2 utilise un seul conteneur et un seul worker.

La première réponse enregistrée est immuable : un rejeu peut donc rester 503 PENDING
après une reprise réussie. Utiliser GET pour l'état courant. Aucun événement terminal
n'est écrit pendant PENDING. La finalisation utilise `UPDATE … WHERE status = 'PENDING'` :
un second passage n'écrit ni nouveau statut ni nouvel événement.

## Persistance et outbox

`orders.orders` est partitionnée par `ordered_at`, mensuellement de janvier 2026 à
décembre 2027, avec partition par défaut. Les identifiants sont TEXT. Commande, lignes,
saga et clé sont créées ensemble. L'intégrité des lignes est contrôlée par cette écriture
applicative : `order_lines` n'a pas `ordered_at` et ne peut donc référencer la clé
composite de la table partitionnée. La lecture ne dépend pas d'une saga, ce qui permet
les commandes historiques du jeu de démonstration.

Statut final, outbox et première réponse sont enregistrés dans une même transaction ;
un échec de l'outbox annule le changement de statut. Le relais verrouille une ligne par
`FOR UPDATE SKIP LOCKED` et ne la marque publiée qu'après l'accusé du broker. Livraison
au moins une fois : les consommateurs dédupliquent par `event_id`. Le topic `orders.events`
est créé à la volée par le broker.

La construction du producteur Kafka, produce, poll et flush passent par un thread.
Une panne Kafka ne bloque ni le démarrage, ni `/readyz`, ni la prise de commandes ;
les événements attendent dans l'outbox et le relais réessaie. Les types d'événement sont
`OrderConfirmed` et `OrderCancelled`, avec `schema_version=1`, selon les schémas JSON 2020-12
versionnés. Le montant confirmé est une chaîne à deux décimales, jamais un flottant.

## Configuration pour l'assemblage

| Variable | Défaut |
|---|---|
| `ENVIRONMENT` | `local` |
| `POSTGRES_HOST` | `postgres` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_DB` | `market` |
| `ORDERS_DB_PASSWORD` | obligatoire, aucun défaut secret ; rôle `orders_svc` |
| `INVENTORY_URL` | `http://inventory:8000` |
| `PAYMENT_URL` | `http://payment:8000` |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` |
| `PAYMENT_TIMEOUT_SECONDS` | `1` |
| `INVENTORY_TIMEOUT_SECONDS` | `1` |
| `RETRY_ATTEMPTS` | `3` |
| `RETRY_BACKOFF_SECONDS` | `0.1`, maximum `0.2` |
| `BREAKER_FAILURE_THRESHOLD` | `3`, au plus `RETRY_ATTEMPTS` |
| `BREAKER_RESET_SECONDS` | `5` |
| `BULKHEAD_MAX_CONCURRENT` | `20`, sans file d'attente |
| `SAGA_STUCK_SECONDS` | `60` |
| `SAGA_RECOVERY_INTERVAL_SECONDS` | `10` |
| `ORDER_STUB_UNIT_PRICE_GBP` | `10.00` |
| `OUTBOX_POLL_SECONDS` | `1` |
| `KAFKA_DELIVERY_TIMEOUT_SECONDS` | `5` |

Le prix unitaire fixe est une **hypothèse temporaire** : montant = somme des quantités
× `ORDER_STUB_UNIT_PRICE_GBP`, sans lecture du catalogue. Le total doit tenir dans
NUMERIC(12,2). Les appels sortants utilisent `market_common.resilience` : retry autour
du circuit autour du délai par tentative, dans un bulkhead sans file ; seules les
pannes techniques sont rejouées et comptées. Une 4xx est un résultat métier.

`ENVIRONMENT=local` active le transfert de `X-Simulate-Failure: payment` vers payment ;
l'en-tête est ignoré dans les autres environnements. Aucun fichier d'environnement
n'est lu par Settings, aucun secret n'a de valeur par défaut.

## Image et vérification

Construire depuis la racine : `docker build -f services/order/Dockerfile -t market-order:dev .`.
L'image Python 3.12.10 installe les seules dépendances d'exécution avec uv, démarre sous
UID 10001, applique `alembic -c /app/services/order/alembic.ini upgrade head`, puis lance
`uvicorn market_order.main:app --host 0.0.0.0 --port 8000 --workers 1`. Les routes
`/healthz` et `/readyz` vérifient respectivement le processus et PostgreSQL.

Dans la pile, le service est démarré par `make up` (profil `core`) et exposé par NGINX sur
`/v1/orders`. Pour un essai isolé, lancer l'image sur le réseau compose du projet avec
les variables ci-dessus et un port publié uniquement sur 127.0.0.1.

`.venv/bin/python -m pytest services/order/tests -q` utilise des doubles HTTP et Kafka,
des doubles transactionnels et SQLite standard pour les requêtes d'accès. Le test d'issue
inconnue déclenche un vrai délai annulé avant de vérifier la reprise. Les essais conteneur
complètent ces tests avec PostgreSQL et Kafka réels.

`python -m market_order.openapi` exporte `contracts/openapi/order.json` sans Settings,
base ni Kafka ; un test vérifie la concordance du fichier avec `app.openapi()`.
