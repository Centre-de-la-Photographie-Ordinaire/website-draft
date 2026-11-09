#!/usr/bin/env bash
# build-diaporama.sh — prépare les visuels du diaporama vitrine
# (static/experiments/nouveau-diaporama/) à partir des fichiers sources.
#
#   usage : tools/build-diaporama.sh [DOSSIER_SOURCE]
#   défaut : /home/alx/org/projects/professional/commundesmortels/gros_fichiers_202611
#
# Les sources existent en trois cadrages, un par famille de terminal :
#   desktop/visuels vitrine _N.jpg             1920×1080  (16:9)
#   middle/visuels vitrine tablette _N.jpg     1024×768   (4:3)
#   mobile/visuels vitrine telephone _N.jpg    1080×1920  (9:16)
#
# Pour chaque source on produit trois largeurs-adaptatives (WebP + JPEG de
# repli) puis on écrit images.json (ordre d'affichage + géométrie des variantes).
# Le navigateur choisit le cadrage correspondant à son écran, puis la variante
# la plus proche de sa densité réelle (cf. main.js).
set -euo pipefail

SRC="${1:-/home/alx/org/projects/professional/commundesmortels/gros_fichiers_202611}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/static/experiments/nouveau-diaporama"

# format → dossier source | préfixe des fichiers | largeurs générées
#
# Les sources font respectivement 1920, 1024 et 1080 px de large : on ne
# fabrique pas de variante plus grande qu'elles (aucun gain, seulement des
# octets). La largeur pleine n'est servie qu'aux écrans à forte densité ; les
# photos du diaporama occupent presque tout l'écran (cf. TARGET_RATIO dans
# main.js), donc les grandes variantes ne sont pas du gaspillage.
FORMATS=(
  "desktop|$SRC/desktop|visuels vitrine _|1920 1280"
  "tablet|$SRC/middle|visuels vitrine tablette _|1024 768"
  "phone|$SRC/mobile|visuels vitrine telephone _|1080 720"
)

JPEG_Q=82
WEBP_Q=78

rm -rf "$OUT/images"
mkdir -p "$OUT/images"

for spec in "${FORMATS[@]}"; do
  IFS='|' read -r name dir prefix widths <<<"$spec"

  # ordre séquentiel d'après le numéro final du nom de fichier (« …_7.jpg »)
  mapfile -t files < <(
    find "$dir" -maxdepth 1 -name '*.jpg' -print | while read -r f; do
      n="$(basename "$f")"; n="${n##*_}"; n="${n%.jpg}"
      printf '%s\t%s\n' "$n" "$f"
    done | sort -n | cut -f2-
  )
  # sources exclues (numéro final du nom de fichier) — « 18 » = visuels
  # vitrine _18, écarté sur demande client (2026-11-09). Exclu ici, à la
  # source, pour que la régénération reste reproductible.
  EXCLUDE="${EXCLUDE:-18}"
  kept=()
  for f in "${files[@]}"; do
    b="${f##*/}"; n="${b##*_}"; n="${n%.jpg}"
    case " $EXCLUDE " in
      *" $n "*) echo "  exclu : $b"; continue ;;
    esac
    kept+=("$f")
  done
  files=("${kept[@]}")
  [ ${#files[@]} -gt 0 ] || { echo "aucune source dans $dir" >&2; exit 1; }

  mkdir -p "$OUT/images/$name"
  echo "== $name : ${#files[@]} visuels (${widths// /px, }px) depuis $dir"

  i=0
  for f in "${files[@]}"; do
    i=$((i + 1))
    stem="$(printf '%02d' "$i")"
    for w in $widths; do
      dest="$OUT/images/$name/${stem}-${w}"
      # JPEG de repli : 4:2:0 + progressif
      convert "$f" -auto-orient -strip -resize "${w}x>" \
        -sampling-factor 4:2:0 -quality "$JPEG_Q" -interlace Plane \
        "$dest.jpg"
      # WebP principal : méthode 6 (recherche lente, meilleur ratio), sans métadonnées
      convert "$f" -auto-orient -strip -resize "${w}x>" \
        -quality "$WEBP_Q" "$dest.webp"
    done
    printf '  %s ← %s\n' "$stem" "$(basename "$f")"
  done
done

# images.json — ordre + géométrie intrinsèque de chaque variante (pour que
# main.js réserve la bonne place et précharge la bonne taille).
python3 - "$OUT" <<'PY'
import json, os, subprocess, sys

out = sys.argv[1]
formats = {
    "desktop": [1920, 1280],
    "tablet":  [1024, 768],
    "phone":   [1080, 720],
}
data = {
    "formats": {
        "desktop": {"aspect": "16:9", "widths": [1920, 1280]},
        "tablet":  {"aspect": "4:3",  "widths": [1024, 768]},
        "phone":   {"aspect": "9:16", "widths": [1080, 720]},
    },
    "images": {},
}
order = []
for fmt, widths in formats.items():
    d = os.path.join(out, "images", fmt)
    stems = sorted({f.split("-")[0] for f in os.listdir(d)})
    items = []
    for s in stems:
        w = next((w for w in widths if os.path.exists(os.path.join(d, f"{s}-{w}.webp"))), widths[-1])
        wh = subprocess.run(
            ["identify", "-format", "%w %h", os.path.join(d, f"{s}-{w}.jpg")],
            capture_output=True, text=True).stdout.split()
        items.append({"stem": s, "base": f"images/{fmt}/{s}", "w": int(wh[0]), "h": int(wh[1])})
        if fmt == "desktop":
            order.append(s)
    data["images"][fmt] = items
data["order"] = sorted(order)

with open(os.path.join(out, "images.json"), "w") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
print("images.json :", {k: len(v) for k, v in data["images"].items()}, "| ordre :", len(data["order"]))
PY

echo "== sortie : $OUT/images — $(du -sh "$OUT/images" | cut -f1)"
