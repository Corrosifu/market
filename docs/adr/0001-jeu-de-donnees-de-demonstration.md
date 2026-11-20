# 0001. Jeu de données de démonstration (paquet Market v3)

- Statut : accepté
- Date : 2026-11-14

## Contexte

Market n'a aucun volume de données : les données de départ ne contiennent que les fixtures dont les tests de la pile ont besoin (comptes `*@market.test`, `SKU-DEMO-1`, `SKU-LAST-1`, `SKU-SELLER-A-1`, `SKU-SELLER-B-1`, `HUB-TEST-10`). Les tests les rétablissent à répétition : elles doivent rester petites, rapides et idempotentes.

Le lakehouse (S5), les tableaux de bord (S6) et la soutenance ont besoin d'un volume crédible, multi-catégories et multi-vendeurs. Un paquet autonome a été retenu : `Market_English_v3.zip` (43,8 Mo, 287 Mo décompressé, SHA-256 `f7c08623b9987bcf8f017daf6d3b0a25bc5131dbc9db6c655854724afef205fc`, bibliothèque standard Python seule).

Ce qui est réel et ce qui ne l'est pas :
- **Réel** (UCI Online Retail II, Chen 2012, https://doi.org/10.24432/C5CG6D, licence CC BY 4.0) : regroupements de factures, noms de produits, quantités, prix unitaires et dates d'origine de 4 136 commandes d'un grossiste britannique d'articles cadeaux. Ce n'est pas une marketplace.
- **Synthétique**, et marqué comme tel sur chaque ligne (`provenance_kind`) : 12 000 commandes `synthetic_order`, 15 des 26 catégories et leurs produits, 60 vendeurs, offres, stock, réservations, paiements, hubs, colis, événements de livraison, bruit d'arrivée et scénario de saturation.
- Les identifiants clients réels sont **pseudonymisés**, pas anonymes. Courriels en `example.invalid`, adresses explicitement fictives.

Volumes : 4 919 produits, 7 406 offres (1 à 3 par produit), 16 136 commandes, 50 919 lignes, 44 986 colis, 375 549 événements canoniques et un flux bruité de 383 177 messages, 8 hubs de 300 colis. Pic d'occupation : `HUB_SYN_01` à 0,92 au point de contrôle du 2026-05-31 12:00 ; les sept autres hubs plafonnent vers 0,2.

Le paquet n'a jamais été importé dans PostgreSQL, MongoDB ou Delta. Sa version 3 est reconstruite à partir de l'extrait brut du paquet v2 (empreinte épinglée), pas du classeur UCI officiel.

## Options étudiées
| Option | Avantages | Inconvénients |
|---|---|---|
| A. Générer nous-mêmes des données entièrement synthétiques | Maîtrise totale, aucun téléchargement | Temps de développement avant le gel du 13 décembre ; aucune donnée réelle à montrer |
| B. Paquet v3, téléchargé et chargé par commande séparée de `make seed` | Volume et provenance documentés, réel et synthétique distingués, bibliothèque standard seule | Téléchargement de 43,8 Mo ; correspondance avec notre modèle à écrire étape par étape |
| C. Classeur UCI brut | Source officielle | Pas de vendeurs, d'offres, de hubs ni de colis : tout le modèle marketplace serait à inventer |
| D. Versionner les données dans le dépôt | Aucun téléchargement | 287 Mo dans Git ; données dans le dépôt public |

## Décision

**Option B**, avec ces règles. Les commandes et fichiers cités ci-dessous (`make seed` et ses données de départ, `make fetch-data`, `make load-demo`, `data/demo/manifest.json`) sont **à livrer** avec les services concernés (étapes S1 à S5) : à la date de cette décision, ils n'existaient pas encore. `make seed`, `make fetch-data`, `make load-demo` et `data/demo/manifest.json` sont livrés en S1 pour le catalogue ; les chargeurs des commandes, du stock, des livraisons et du lakehouse suivent en S2 à S5.

1. **Deux jeux distincts.** `make seed` reste le jeu de fixtures des tests, inchangé. Le jeu de démonstration se charge par `make load-demo PROFILE=ci|demo`, avec des identifiants qui ne recouvrent jamais ceux des fixtures (`PRD_…`, `SELLER_SYN_…`, `OFFER_SYN_…`, `ORD_…`, `SHIP_SYN_…`, `HUB_SYN_…`). Aucun test existant ne dépend du jeu de démonstration.
2. **Aucune donnée versionnée.** Le zip est publié comme asset de release du dépôt public `market` (tag `dataset-v3`). `make fetch-data` le télécharge, vérifie le SHA-256 épinglé dans `data/demo/manifest.json`, l'extrait dans un cache ignoré par Git, puis lance le `verify.py` du paquet, seulement après le contrôle d'empreinte. Bibliothèque standard seule.
3. **Scripts du paquet non intégrés.** `generate.py`, `catalog_syn.py`, `source_tools.py`, `verify.py` et `replay.py` restent dans le zip, qui garde ainsi sa provenance. Le dépôt contient seulement notre chargeur.
4. **Profils.** `demo` charge le paquet entier, 12 000 commandes synthétiques comprises (volume, 26 catégories vendues). `ci` charge un sous-ensemble déterministe d'environ 300 commandes, fermé sur les clés étrangères (vendeurs, produits, offres, colis et événements des commandes retenues). Pas de repli entièrement synthétique : le générateur exige le paquet v2. Si le zip est indisponible, la démonstration tourne sur les fixtures et le simulateur, avec un message explicite.
5. **Chargement sans dépendance nouvelle.** PostgreSQL par `\copy` dans le conteneur `postgres` ; MongoDB par `mongoimport` (présent dans l'image `mongo:7.0.18`). Le chargement est idempotent : relancé, il ne crée aucun doublon.
6. **Import, pas opération métier.** Les commandes historiques sont chargées dans leur état final : elles ne passent ni par la Saga ni par l'outbox et ne publient aucun événement. Le flux temps réel de la démonstration vient du simulateur, qui sait rejouer `event_deliveries` avec un facteur d'accélération. La saturation en direct reste portée par le simulateur de S4.
7. **Provenance conservée** : une colonne (ou un champ) `provenance_kind` sur chaque table chargée, pour distinguer réel et synthétique devant le jury.

Correspondance avec le modèle Market :

| Paquet | Market | Étape |
|---|---|---|
| `sellers.csv`, `products.jsonl`, `offers.csv`, `schemas/product_*.schema.json` | MongoDB `sellers`, `products`, `offers` ; schémas convertis dans `services/catalog/schemas/<categorie>.json` | S1 |
| `orders.csv`, `order_items.csv`, `payments.csv` | `orders.orders`, `orders.order_lines`, schéma `payment` | S2 |
| `inventory.csv`, `stock_reservations.csv`, `inventory_movements.csv` | `inventory.stock` (`sku` = `offer_id`), réservations, mouvements | S2 |
| `hubs.csv`, `carriers.csv`, `shipments.csv`, `shipment_items.csv`, `delivery_events.csv` | schéma `delivery` | S3 |
| `event_deliveries.csv` | rejeu par le simulateur | S3 |
| `raw/transactions.csv` et tables | zone `raw` du lakehouse | S5 |

Écarts traités explicitement :
- `RETURN_PROCESSED` (1 327 événements) n'est pas un statut Market : il n'est pas chargé dans `delivery`, il reste en zone raw. Aucun statut n'est ajouté.
- Les données contiennent `FAILED_ATTEMPT → AT_HUB` (4 778) et `OUT_FOR_DELIVERY → RETURNED` (1 327) : la machine à états de S3 doit les accepter.
- Horodatages sans fuseau : chargés comme UTC (**hypothèse**).
- Devise GBP conservée telle quelle, sans conversion.
- `SHA256SUMS` du paquet écrit ses chemins avec des `\` (paquet produit sous Windows) : le `verify.py` d'origine échoue sous macOS et Linux. Le chargeur réécrit seulement les séparateurs de cet index dans la copie extraite, après le contrôle du SHA-256 du ZIP et en refusant tout chemin absolu, `..` ou `:`, puis lance `verify.py` tel quel. Le contrôle reste équivalent : les 63 empreintes ne changent pas, l'index n'est pas lui-même haché et le ZIP épinglé reste l'ancre d'intégrité. Aucun paquet corrigé n'est publié (décision du 2026-11-19).
- Les huit hubs du paquet n'ont pas de hiérarchie : ils sont chargés comme hubs locaux, en plus des hubs de démarrage de S3. Leur capacité (300 colis) est une donnée du paquet ; le seuil de 85 % reste une **hypothèse** lue de la configuration.
- `customer_id` du paquet, déjà pseudonymisé à la source, reste une donnée personnelle indirecte : il est re-pseudonymisé (HMAC-SHA256, `PSEUDONYMIZATION_KEY`) dès staging, comme `customer_pseudo_id`.

## Conséquences

- Un chargeur par étape, chacun après les migrations de son service ; un test d'intégration par chargeur (« chargement `ci` idempotent, comptes conformes au manifeste »).
- Prévu : la CI d'intégration téléchargera le zip (cache des Actions) pour charger le profil `ci` ; elle ne chargera jamais le profil `demo`. Ce n'est pas encore en place à la fin de S1.
- Le README public cite la source UCI et la licence CC BY 4.0, et dit ce qui est synthétique.
- Le vocabulaire est imposé : « pseudonymisé », jamais « anonyme » ; « synthétique » pour tout ce qui n'est pas observé.
- Limites à dire à l'oral : un seul hub saturé dans le jeu ; source britannique d'articles cadeaux, pas une marketplace ; produits synthétiques peu variés ; v3 non reconstruite depuis le classeur UCI officiel.

## Alternative écartée à citer à l'oral

Charger le volume avec les données de départ : les tests de la pile rétablissent ces données à répétition, et leurs fixtures rares (dernier article, hub de capacité 10) seraient noyées dans 16 000 commandes. Séparer fixtures et démonstration garde des tests rapides et déterministes.
