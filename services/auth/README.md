# Service auth

`POST /v1/auth/login` renvoie un JWT RS256 et `Cache-Control: no-store`.
La durée de vie vient de `JWT_TTL_SECONDS`, avec un défaut de 900 secondes.
Le `kid` est l'empreinte SHA-256 de la clé publique RSA encodée en DER.
`GET /.well-known/jwks.json` expose uniquement la clé publique.

`GET /v1/auth/verify` est réservé au réseau compose. Il répond 204 avec
`X-User-Id` et `X-User-Role`, ou 401. Il impose RS256, un `kid` connu,
une signature locale valide, `exp`, `iss`, `aud`, `sub` et un rôle reconnu.
Les en-têtes `jku`, `x5u` et `jwk` ne fournissent aucune clé au vérificateur.

## Démarrage et stockage

Le service utilise uniquement le schéma PostgreSQL `auth` via `auth_svc`.
Alembic applique les migrations avant de lancer l'application. Le démarrage
rétablit les trois comptes de démonstration avec la même fonction que
`python -m market_auth.seed`, appelée par `make seed`. Les UUID sont stables,
calculés avec `uuid5(NAMESPACE_URL, "market:" + email)`. Les insertions et
mises à jour des comptes sont transactionnelles. Chaque rétablissement
remplace les mots de passe par leurs hachages Argon2id, depuis les variables
`DEMO_CLIENT_PASSWORD`, `DEMO_SELLER_PASSWORD`, `DEMO_OPS_PASSWORD`.
Le rétablissement est refusé hors de `ENVIRONMENT=local`.

Préparer les secrets avant `make up`. Les deux clés sont montées
dans `/run/secrets`. L'entrypoint démarre en root pour copier les fichiers
dans le tmpfs `/run/keys`, avec un répertoire 0700 et des clés 0600 appartenant
à l'UID 10001. `setpriv` lance ensuite Alembic et uvicorn avec cet UID et
sans groupes supplémentaires. Le processus applicatif possède son répertoire
personnel `/home/market`, notamment pour les recherches de certificats d'asyncpg.
La clé privée demeure dans les montages et la mémoire du conteneur.

L'image utilise `python:3.12.10-slim` et `uv==0.13.8`. L'installation suit
`uv sync --frozen --package market-auth`. Le contexte Docker exclut les
secrets, l'environnement local, les caches et les métadonnées Git.
Le port 8000 est interne au réseau compose. `/healthz` et `/readyz` sont
fournis par `market_common`, avec une sonde PostgreSQL pour la préparation.

## Limitation des connexions

Les e-mails sont normalisés en minuscules et leurs espaces sont retirés.
Après `AUTH_MAX_FAILURES` échecs, défaut 10, dans une fenêtre glissante de
`AUTH_FAILURE_WINDOW_SECONDS`, défaut 300, la clé reçoit 429 avec `Retry-After`.
Le même traitement s'applique à un compte inconnu et à un compte existant.
Les tentatives simultanées d'une même clé sont sérialisées. Une connexion
réussie remet son compteur à zéro. Les autres e-mails conservent leur compteur.

Compte inconnu et mot de passe faux reçoivent le même 401 et le même message.
Un compte inconnu déclenche une vérification Argon2id contre un hachage factice.
Les paramètres sont ceux du `PasswordHasher` d'argon2-cffi, avec au plus
`AUTH_HASH_CONCURRENCY` vérifications simultanées, défaut 2, pour borner
la mémoire nécessaire à Argon2 dans le conteneur de 384 Mio.

La file Argon2 accepte au plus `AUTH_HASH_MAX_WAITING` opérations en attente,
défaut 16, en plus des opérations actives. L'acquisition d'un emplacement
expire après `AUTH_HASH_WAIT_TIMEOUT_SECONDS`, défaut 0,25 seconde.
Une file pleine ou un délai dépassé renvoie 503 avec `Retry-After`, réglé
par `AUTH_HASH_RETRY_AFTER_SECONDS`, défaut 1 seconde. Ce rejet de capacité
ne compte pas comme un mauvais mot de passe. Une opération déjà lancée
conserve son emplacement jusqu'à la fin du thread, même si sa requête est annulée.

Le compteur suit au plus `AUTH_FAILURE_MAX_ENTRIES` e-mails, défaut 10 000.
À capacité atteinte, il évince la clé dont le dernier échec est le plus ancien.
Une clé évincée perd son historique, puis repart sans échec à la prochaine tentative.

Le compteur reste en mémoire avec **un seul worker uvicorn**. Il est remis à
zéro au redémarrage et nécessite un stockage partagé avant toute réplication.
Un tiers peut verrouiller un compte de démonstration pendant la fenêtre.
NGINX ajoute une garde IP de 50 requêtes/seconde, avec `burst=200 nodelay`,
afin que les 80 tentatives d'un même e-mail soient traitées par la limite auth.

## Passerelle et vérification

NGINX résout `auth` et `catalog` à la requête via le DNS Docker. Le catalogue
peut être absent au démarrage. Toutes les routes `/v1/` passent par
`auth_request`, à l'exception exacte du login. JWKS est public et le chemin
de vérification externe renvoie 404. Les en-têtes d'identité du client sont
écrasés sur les routes protégées et les routes publiques. Les sous-requêtes
de vérification utilisent GET sans corps. L'indisponibilité d'auth devient
503 et les erreurs 500 renvoyées par les services restent des erreurs 500.
NGINX masque sa version et ajoute `X-Content-Type-Options: nosniff` et
`X-Frame-Options: DENY` sur toutes ses réponses, y compris les erreurs.
Les réponses de validation 422 conservent les chemins et les messages d'erreur,
en retirant les champs `input` et `ctx` qui pourraient contenir la valeur soumise.
Le buffering est désactivé sur `/v1/stream/`. Cette route sera raccordée à
son service lors de l'étape de streaming.

Les tests unitaires se lancent avec `uv run --frozen pytest services/auth/tests/unit`.
Après `make up`, lancer les tests additionnels de runtime avec
`uv run --frozen pytest services/auth/tests/integration`.
Ils vérifient les permissions de la copie des clés, l'identité du processus,
le rétablissement en base et l'absence de verrouillage des autres e-mails.
Le test de rétablissement modifie temporairement le hachage du compte client
puis rétablit les comptes, y compris dans son nettoyage.

Le contrat est exporté depuis `market_auth.main.create_app().openapi()` dans
`contracts/openapi/auth.json`. Les routes de documentation interactives sont
désactivées.
