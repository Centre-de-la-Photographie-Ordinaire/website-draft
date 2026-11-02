# diaporama vitrine — chaîne de fabrication

La page vitrine (`static/experiments/nouveau-diaporama/`) affiche une photo
toutes les deux secondes. Les visuels viennent de
`/home/alx/org/projects/professional/commundesmortels/gros_fichiers_202611/`,
qui contient **trois montages du même sujet**, un par famille de terminal :

| dossier source | cadrage | dimensions |
|---|---|---|
| `desktop/` — `visuels vitrine _N.jpg` | 16:9 | 1920 × 1080 |
| `middle/` — `visuels vitrine tablette _N.jpg` | 4:3 | 1024 × 768 |
| `mobile/` — `visuels vitrine telephone _N.jpg` | 9:16 | 1080 × 1920 |

20 visuels par montage, numérotés `_1` … `_20` (l'ordre d'affichage suit le
numéro, pas l'ordre alphabétique).

## régénérer

```sh
tools/build-diaporama.sh                  # utilise le dossier source par défaut
tools/build-diaporama.sh /autre/dossier   # ou un dossier explicite
```

Le script réécrit intégralement `static/experiments/nouveau-diaporama/images/`
et `images.json`. Il exige ImageMagick (`convert`).

Ce qui est produit, pour chaque visuel :

| montage | largeurs servies | WebP ≈ | JPEG repli ≈ |
|---|---|---|---|
| desktop | 1920, 1280 | 115 ko / 65 ko | 235 ko / 121 ko |
| tablet | 1024, 768 | 57 ko / 38 ko | 103 ko / 65 ko |
| phone | 1080, 720 | 100 ko / 58 ko | 211 ko / 111 ko |

Pas de variante plus large que la source : les fichiers d'origine font 1920,
1024 et 1080 px de large, agrandir n'apporterait aucun détail.

Poids total du dossier généré : ~31 Mo pour les 3 montages × 20 visuels
(WebP + JPEG de secours de chaque taille). **Une visite ne télécharge qu'une
poignée d'images**, une par photo affichée, dans le seul montage retenu.

## comment le navigateur choisit

`main.js` :

1. **le montage** — d'après `innerWidth` / `innerHeight` :
   - portrait, écran < 640 px, ou fenêtre très basse (< 500 px) → **phone** (9:16)
   - ratio < 1,55 → **tablet** (4:3)
   - sinon → **desktop** (16:9)
   Le montage est figé après ~350 ms (le temps que la barre d'URL mobile se
   stabilise) et ne change plus qu'en cas de rotation ou de redimensionnement.
2. **la largeur** — `devicePixelRatio` (plafonné à 2) × la taille d'affichage
   prévue, arrondie à la variante disponible la plus proche.
3. **le format** — WebP quand le navigateur le supporte (testé une fois via
   canvas), sinon le JPEG.

La photo est dimensionnée par `main.js` en **plein cadre** (bord à bord, toute
la fenêtre), puis `object-fit: cover` absorbe l'écart résiduel entre le cadrage
et l'écran. La barre logo/‹ › flotte par-dessus la photo, en bas à gauche, avec
un fond diffus pour rester lisible quelle que soit l'image.
Les préchargements `<link rel=preload>` de `index.html` suivent la même logique
de montage que `main.js` ; si on modifie les seuils de `main.js`, les mettre à
jour ici aussi.

## propriétés des fichiers

- ordre source conservé (numéro du nom de fichier) ;
- EXIF supprimé (`-strip`), orientation appliquée avant suppression ;
- JPEG : progressif, 4:2:0, qualité 82 ;
- WebP : qualité 78, méthode 6 ;
- géométrie intrinsèque de chaque variante inscrite dans `images.json`, ce qui
  permet à `main.js` de réserver la bonne place avant chargement.
