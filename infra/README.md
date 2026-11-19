# Pile locale

Copier `.env.example` vers `.env` et y remplacer les valeurs, puis `make up` démarre
PostgreSQL, MongoDB, Kafka JVM (KRaft à un broker), les services `auth` et `catalog`
et NGINX dans le profil `core`.
`make down` arrête les conteneurs en conservant les volumes.

La passerelle répond sur http://localhost:8080/ et `/healthz`.
MongoDB, sans authentification en local, est accessible sur le réseau compose
et sur `127.0.0.1:27017` uniquement : limite assumée, décrite dans le README du catalogue.
Kafka annonce `kafka:9092` aux clients compose et `localhost:29092` aux outils
de l'hôte. Le contrôleur reste interne, sur 9093.

## PostgreSQL

L'image initialise la base `market` et les six rôles seulement sur un volume
vide. Chaque rôle possède son schéma, peut se connecter à `market`, et ne
dispose d'aucun droit sur les autres schémas ou sur `public`.
Le script échoue si un mot de passe manque et utilise les littéraux échappés
de psql. Aucun mot de passe n'est embarqué dans le SQL ou le compose.

Vérifier l'isolation avec :
`docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d market < infra/postgres/tests/check-isolation.sql`.
Le contrôle vérifie les propriétaires, la connexion, les droits du schéma
propre et l'absence de droits croisés, de création de base ou de rôle.

Après une modification de l'initialisation, on peut la rejouer avec
`docker compose --profile core down -v`, puis `make up`.
**Cette commande détruit les données locales de tous les volumes de la pile.**

## Versions et ressources

`infra/versions.env` documente les versions et leurs sources de compatibilité.
Les tags du compose sont explicites et contrôlés par les tests d'architecture.
Spark et MinIO ne font pas partie du profil `core` ; leur compatibilité de bout
en bout sera éprouvée avec le streaming et le lakehouse. MinIO est archivé en
amont ; sa dernière release source est épinglée, la disponibilité du tag
d'image reste à valider.

Les plafonds mémoire du profil `core` totalisent 3584 Mio : PostgreSQL 512,
MongoDB 768, Kafka 1536, auth 384, catalogue 256, NGINX 128. Le heap Kafka
est limité à 512 Mio et le cache WiredTiger à 0,25 Gio. Ces plafonds
dépassent d'environ 0,5 Go l'objectif d'environ 3 Go fixé en S0 (hypothèse) ;
ce sont des maxima, pas une consommation : mesurer avec
`docker stats --no-stream` après démarrage, puis sous charge.

Mesure du 14 novembre 2026 au repos (Docker Desktop) : PostgreSQL 24,71 Mio,
MongoDB 86,25 Mio, Kafka 405,8 Mio, NGINX 7,20 Mio, soit environ 524 Mio
hors moteur Docker. Ce relevé ne valide pas la consommation sous charge.

Le script d'initialisation doit être exécutable (bit versionné dans Git).
L'initialisation et le contrôle d'isolation sont vérifiés sur un volume neuf.
