#!/usr/bin/env bash
# build-agenda.sh — prépare les affiches de la page /agenda/
#
#   usage : tools/build-agenda.sh [DOSSIER_SOURCE]
#   défaut : /home/alx/org/projects/professional/commundesmortels/page agenda
#
# Pour chaque affiche (JPEG 3508 × 4782, imprimée en A2) on produit :
#   static/images/agenda/<slug>-<largeur>.jpg   vignette + affiche du dialog
#   static/documents/agenda/<slug>.pdf          le PDF téléchargeable
# et on affiche la liste des fichiers écrits.
#
# Les sources pèsent 3 à 15 Mo et les PDF jusqu'à ~3 Mo : rien de tout ça ne
# part tel quel dans une page. La vignette est en 600 px (≈ 40 ko), la version
# du dialog en 1000 px ; le PDF est copié tel quel (c'est lui que le visiteur
# télécharge s'il veut tout le détail).
set -euo pipefail

SRC="${1:-/home/alx/org/projects/professional/commundesmortels/page agenda}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG="$ROOT/static/images/agenda"
DOC="$ROOT/static/documents/agenda"

# slug | fichier image source | fichier pdf source
AFFICHES=(
  "cest-une-femme|affiche c'est une femme qualité optimale.jpg|affiche c'est une femme.pdf"
  "maison-et-jardin|affiche maison et jardin.jpg|affiche maison et jardin.pdf"
  "chien-et-chat|affiche chien et chat.jpg|affiche chien et chat.pdf"
)

JPEG_Q=82

mkdir -p "$IMG" "$DOC"
rm -f "$IMG"/*.jpg "$DOC"/*.pdf

for spec in "${AFFICHES[@]}"; do
  IFS='|' read -r slug jpg pdf <<<"$spec"

  [ -f "$SRC/$jpg" ] || { echo "image manquante : $SRC/$jpg" >&2; exit 1; }
  [ -f "$SRC/$pdf" ] || { echo "pdf manquant : $SRC/$pdf" >&2; exit 1; }

  for w in 600 1000; do
    convert "$SRC/$jpg" -auto-orient -strip -resize "${w}x>" \
      -sampling-factor 4:2:0 -quality "$JPEG_Q" -interlace Plane \
      "$IMG/${slug}-${w}.jpg"
  done

  cp "$SRC/$pdf" "$DOC/${slug}.pdf"

  printf '  %-16s %s -> %s (vignette %s, affiche %s, pdf %s)\n' "$slug" \
    "$jpg" "$pdf" \
    "$(du -h "$IMG/${slug}-600.jpg" | cut -f1)" \
    "$(du -h "$IMG/${slug}-1000.jpg" | cut -f1)" \
    "$(du -h "$DOC/${slug}.pdf" | cut -f1)"
done

echo "== images : $IMG ($(du -sh "$IMG" | cut -f1))"
echo "== documents : $DOC ($(du -sh "$DOC" | cut -f1))"
