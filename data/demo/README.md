# Jeu de démonstration Market v3

`make fetch-data` télécharge l'asset épinglé dans `manifest.json`, contrôle son
SHA-256, puis exécute `python -B verify.py` du paquet. Un ZIP correct déjà
présent dans `.cache/` est réutilisé sans accès réseau. Un ZIP dont l'empreinte
diffère est refusé avant toute extraction ou exécution.

Le ZIP reste en cache. Chaque utilisation extrait une copie temporaire neuve,
la vérifie et la supprime en quittant la commande. Les scripts du paquet
restent ceux de l'archive. Le paquet v3 contient des séparateurs Windows dans
`SHA256SUMS` ; les noms de chemins de cette seule copie temporaire de l'index
sont adaptés à l'OS. Les empreintes, les données et `verify.py` sont conservés
à l'identique. Le vérificateur original contrôle les 63 fichiers et la
couverture complète de son index. Le ZIP épinglé est conservé octet pour octet.

## Profils et correspondance

`make load-demo PROFILE=ci` charge le catalogue des 300 commandes dont les
identifiants sont les premiers dans l'ordre lexicographique. Il retient leurs
produits, toutes les offres de ces produits, les vendeurs de ces offres et
le premier vendeur de chaque produit. Ce profil contient 1 669 lignes de
commande, 887 produits, 1 341 offres et 30 vendeurs sur 11 catégories.
Le même sous-ensemble détermine les commandes et leurs lignes chargées dans PostgreSQL.

`make load-demo PROFILE=demo` charge les 4 919 produits, 7 406 offres et
60 vendeurs du paquet entier, ainsi que ses commandes, paiements et stocks. `make up-demo` démarre la pile puis télécharge,
vérifie et charge ce profil complet. Un téléchargement indisponible est
signalé et la pile continue avec les fixtures locales. Une erreur d'intégrité,
de validation ou d'import termine la commande avec un code non nul.

Les identifiants `PRD_`, `SELLER_SYN_` et `OFFER_SYN_` restent ceux du paquet.
Les produits utilisent `name` comme `title`, `category_id` comme `category`,
le premier `seller_ids` comme `seller_id` et conservent leurs attributs.
Dans `electronics`, `synthetic_brand` fournit `attributes.brand`.
Les offres utilisent le prix de référence du produit en GBP, calculé avec
`Decimal` et arrondi au centime avec `ROUND_HALF_UP`. Les prix du paquet
possèdent déjà deux décimales. Les champs étrangers au modèle du catalogue
ne sont pas importés. Chaque document conserve son `provenance_kind` et
reçoit la date déterministe `2026-05-01T00:00:00Z` au type BSON date.

## Schémas et import

Les 26 schémas convertis sont versionnés dans `services/catalog/schemas/`.
Ils gardent les contraintes des attributs du paquet, avec les types BSON
adaptés. `books` et `electronics` forment une union avec les fixtures.
Les attributs du paquet y sont optionnels, `electronics` exige toujours
`brand` et `warranty_months`, et un ISBN fourni dans `books` garde son motif.
Les attributs d'une autre catégorie restent refusés.

Pour régénérer les schémas depuis le paquet vérifié, lancer
`python3 -m data.demo schemas`, puis relire les changements versionnés.

Avant chaque import, le chargeur reconstruit et démarre le catalogue avec
`docker compose up -d --build --wait catalog`. Son démarrage applique les
validateurs depuis l'image reconstruite. Le chargeur copie ces validateurs
dans trois collections temporaires et les impose à `mongoimport`.
Un rejet fait échouer la commande avec le nom de la collection et le nombre
de rejets, avant publication dans les collections actives.

Après validation de toutes les préparations, les documents sont publiés
par lots avec upsert, parents avant enfants. Les anciens documents du jeu
absents du profil sont retirés, enfants avant parents, en filtrant strictement
leurs préfixes. Ainsi, passer de `demo` à `ci` retrouve les comptes du manifeste
et préserve les fixtures et les autres documents. Une interruption pendant
la publication peut laisser une union partielle des profils ; relancer la
même commande réconcilie cet état. La publication multicollection n'est pas
une transaction. Les collections temporaires sont supprimées en fin de commande.
Deux imports simultanés depuis le même checkout sont refusés par un verrou
de fichier libéré automatiquement à la fermeture du processus. Des imports
depuis plusieurs checkouts vers la même base doivent être coordonnés.

## Commandes, paiements et stock (S2)

Après le catalogue, la même commande charge les six tables PostgreSQL ;
`make up-demo` utilise aussi ce chemin. Lancer d'abord `make up` pour appliquer
les migrations des services `order`, `payment` et `inventory`. Une table
absente fait échouer l'import avec l'indication de lancer `make up`.

| Lignes chargées | `ci` | `demo` |
|---|---:|---:|
| Commandes | 300 | 16 136 |
| Lignes de commande | 1 669 | 50 919 |
| Paiements | 344 | 17 463 |
| Positions de stock | 1 341 | 7 406 |
| Réservations | 160 | 901 |
| Mouvements | 22 590 | 59 834 |

Le lecteur réutilise `read_catalog`, ses commandes et ses offres retenues.
Les lignes et paiements suivent les commandes ; stock, réservations et
mouvements suivent les offres. La correspondance `sku = offer_id` utilise
le couple produit/vendeur pour les lignes, le triplet produit/vendeur/hub
pour le stock. Une référence absente du paquet est une erreur explicite,
même si elle se trouve hors de la sélection `ci`. Un mouvement d'une offre
retenue peut référencer une ligne d'une commande non retenue : son
`order_item_id` est alors chargé à `NULL` en `ci`. Les réservations du paquet
ont toujours `order_id` nul.

Les commandes portent `status=CONFIRMED`, le statut du paquet dans
`historical_status` et `merchandise_total_gbp` dans `total_gbp`. Les quantités
et `unit_price_gbp` des lignes sont conservés séparément, sans conversion
par flottant. Paiements : captures et remboursements, statut `SUCCEEDED`,
`payment_at` vers `created_at`. Stock : `available_quantity`,
`reserved_quantity` et `on_hand_quantity` vers `available`, `reserved` et
`on_hand`, `snapshot_at` vers `updated_at`. Tous les horodatages sans fuseau
sont interprétés comme UTC (**hypothèse de l'ADR 0001**) et écrits avec un
fuseau explicite ; la session psql utilise aussi UTC. La devise reste GBP.
Les identifiants clients sont pseudonymisés à la source et restent des
données personnelles indirectes.

Le script `.cache/postgres.sql` est écrit en octets UTF-8, fins de ligne LF,
et passé tel quel à une seule session `psql -v ON_ERROR_STOP=1`. Ses six
`\copy … FROM STDIN` incluent les données dans le script. Une transaction
contrôle la présence des tables avant toute suppression, retire uniquement
les lignes `provenance_kind IS NOT NULL`, puis charge les parents avant les
enfants. Mouvements et réservations sont supprimés avant le stock. Les
contraintes `CHECK` restent actives ; une erreur SQL annule la transaction.
Les fixtures et les commandes API, dont la provenance est nulle, sont
préservées. Les comptes relus dans les tables sont comparés au manifeste,
comme ceux du catalogue. Les deux sens de changement de profil retirent
les anciennes lignes du jeu. Aucun import n'écrit dans `saga_instances`,
`outbox` ou `idempotency_keys`, et aucun événement n'est publié.

La publication MongoDB et la transaction PostgreSQL sont successives,
sans transaction distribuée : si PostgreSQL échoue après publication du
catalogue, la commande échoue et doit être relancée. Le script du cache
contient les données pseudonymisées du profil ; il n'est jamais versionné.

## Tests et provenance

`uv run --frozen pytest data/demo/tests -m "not live"` teste le téléchargement authentifié,
la sélection fermée, la correspondance, les schémas et les erreurs d'import.
Après `make up`, le test marqué `live` vérifie également le rejet réel d'un
ISBN invalide par MongoDB et la conservation des collections actives.
Le chargeur s'exécute avec la bibliothèque standard Python seule.

La source historique est UCI Online Retail II, Chen 2012, sous licence
CC BY 4.0. Les noms, quantités, prix et regroupements de factures observés
proviennent d'un grossiste britannique d'articles cadeaux. Les vendeurs,
offres, 15 catégories et les données de fonctionnement de la marketplace
sont synthétiques. Les identifiants clients sont pseudonymisés. La version 3
est reconstruite depuis l'extrait brut du paquet v2. Le paquet conserve ses
fichiers de licence, ses rapports et sa provenance dans l'archive.

Source UCI : https://doi.org/10.24432/C5CG6D
