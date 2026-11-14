# Charte graphique de Market

Direction : **utilitaire calme**, une interface silencieuse à accent unique. Base : le système de design open source *apple-design-system* (rukkiecodes, licence MIT), inspiré des principes de design minimaliste de produit, adapté au web et à l'accessibilité. Aucun lien avec une marque : aucun logo, aucune mise en page copiée. Choix motivé : l'interface sert à décider et à surveiller en direct, la lisibilité d'un état prime sur l'effet.

Source unique des valeurs : `frontend/src/styles/tokens.css`. Cette charte explique comment s'en servir.

## Principes
1. **Un message par écran.** Un titre, une action principale. L'écran opérations est organisé autour d'une décision : « quel hub risque la saturation ? ».
2. **Un seul accent.** Bleu d'action `#0066cc`. Gris structurels. Vert, ambre et rouge sont réservés aux statuts (hub normal, proche du seuil, saturé ; flux sain, vieillissant, arrêté), jamais décoratifs.
3. **Boutons en pastille.** Actions principales, champs de recherche et filtres : rayon `--radius-pill`. Un seul bouton principal (accent plein) par vue, les autres en contour.
4. **Pas d'ombre de structure.** La profondeur vient du changement de surface (blanc, gris clair, gris très clair) et de filets de 1 px. Seule ombre : `--shadow-media`, sous une image héros ou produit.
5. **Trois graisses : 400, 600, 700.** Corps 400, libellés 600, titres 700. La graisse 500 est interdite. Titres à interligne serré et léger resserrement.
6. **Filets, pas de bordures épaisses.** 1 px gris clair ; 2 px réservés à l'élément sélectionné ou au focus.
7. **Espace avec intention.** Grille de 8 px, gouttière de 24 px sur grand écran et 16 px sur mobile. Large autour d'une idée, serré entre contrôles liés.
8. **Mouvement utile.** 150 à 240 ms, une transition indique un changement d'état. `prefers-reduced-motion` coupe tout.
9. **Images réelles.** Captures d'écran et graphiques construits à partir des données ; pas d'illustration décorative.

## Couleurs (clair / sombre, contrastes vérifiés en test)
| Rôle | Jeton | Usage |
|---|---|---|
| Fond | `--color-bg` | page |
| Surface | `--color-surface`, `--color-surface-raised` | tuiles alternées, champs, puces |
| Filets | `--color-border`, `--color-divider` | séparations de 1 px |
| Texte | `--color-text`, `--color-text-secondary` | contenu, aide |
| Accent | `--color-accent` (+ `-focus`, `-soft`, `-contrast`) | action principale, lien, sélection, focus |
| Statuts | `--color-ok`, `--color-warn`, `--color-critical` (+ `-soft`) | sens uniquement |

Écarts par rapport au système d'origine, volontaires : le texte secondaire et les couleurs de statut sont plus sombres en mode clair, parce que les valeurs d'origine n'atteignent pas 4,5:1 sur fond blanc ; la police est celle du système (pas de police externe). Règle : contraste texte/fond ≥ 4,5:1 ; une information n'est **jamais portée par la couleur seule** (ajouter un libellé : « Saturé 92 % »).

## Composants
- **Boutons** : pastille, cible ≥ 44 px, focus visible (anneau `--color-accent-focus`).
- **Cartes** : `--radius-card`, surface différente du fond, filet de 1 px, 20 à 24 px de marge interne, sans ombre.
- **Tableaux** : chiffres alignés à droite en police à chasse fixe, en-têtes en légende grise, filets légers.
- **Indicateur de statut** : pastille + libellé, fond `-soft`, texte de la couleur de statut. Actif : badge accent plein ; terminé ou neutre : badge gris.
- **Confirmations et menus** : boîte de dialogue centrée et feuille basse personnalisées, pas de `alert()` du navigateur.
- **États** : vide, chargement (squelette), erreur et **donnée périmée** (`data_age_seconds` au-dessus du seuil) sont dessinés dès le début. Un flux arrêté doit se voir à l'écran.
- **Mobile** : pas de défilement horizontal de page.

## Écrans
Client : catalogue, panier et commande, suivi d'une commande (frise de statuts). Opérations : hubs (jauge de saturation et seuil lu de la configuration), retards, alertes, âge de la donnée.

## À ne pas faire
Second accent, ombre sur une carte, graisse 500, couleur ou taille en dur dans un composant, police chargée depuis un serveur externe, slogans creux, chiffres de performance inventés.
