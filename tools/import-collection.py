#!/usr/bin/env python3
"""
import-collection.py — importe le répertoire de la collection « le commun des
mortels » dans le site.

   usage : tools/import-collection.py [options] [DOSSIER_SOURCE]

   DOSSIER_SOURCE : racine du répertoire ; un sous-dossier par collection.
                    défaut : /home/alx/code/centre-de-la-photographie-ordinaire/répertoire/

Pour chaque image source :
  1. recadrage des bords blancs / unis (papier du scan, passe-partout) —
     cf. « recadrage » plus bas ;
  2. réduction dans le cadre 4:3 paysage de la page collection, ratio
     constant, photo centrée sur la marge grise unie #AEAEAE (une photo
     portrait est posée debout au centre : elle n'est ni déformée ni rognée) :
        vignette 480x360   grande image 2000x1500 ;
  3. écriture en WebP (qualité réglable) de deux variantes :
        <slug>/<slug>-NN-thumb.webp   bandeau de vignettes
        <slug>/<slug>-NN-large.webp   grande image

Puis écrit l'index lu par la page :
        static/collection/collections.json

Le script est idempotent : une image est sautée quand ses deux sorties sont
plus récentes que la source (option --force pour tout refaire). Les collections
disparues du répertoire sont retirées de static/collection/ (option --keep pour
les conserver).

Options
  --only SLUG      ne traiter qu'une collection (répétable) ; slug = nom du
                   dossier normalisé (ex. « pti-oizo »)
  --force          refaire même les images déjà à jour
  --dry-run        afficher ce qui serait fait, sans rien écrire
  --keep           ne pas supprimer les dossiers de collections absentes
  --quality-large  qualité WebP de la grande image (défaut 78)
  --quality-thumb  qualité WebP de la vignette (défaut 72)
  --workers N      encodages ImageMagick en parallèle (défaut : CPU - 1)

Dépendances : Python 3 + Pillow (recadrage), ImageMagick 7 (`magick`, encodage
et rééchantillonnage de qualité).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent  # website-draft/
DEFAULT_SRC = Path(
    "/home/alx/code/centre-de-la-photographie-ordinaire/répertoire"
)
OUT_ROOT = ROOT / "static" / "collection"
# empreinte de la recette de cadre (cf. fresh()) : sert seulement à invalider
# les images déjà générées quand la recette change.
STAMP_NAME = "recette.txt"
# Hugo lit data/collection.json comme site.Data.collection (cf.
# layouts/partials/galerie.html) : l'index y est écrit en plus de celui de
# static/collection/.
DATA_INDEX = ROOT / "data" / "collection.json"

# formats de sortie — le fond gris clair est ajouté par le CSS autour de
# l'image ; ces dimensions sont donc celles de l'image elle-même.
# Un seul format de cadre, en PAYSAGE (retour client 2026-11-09 : « every
# picture should be in landscape mode »). Une photo portrait est posée debout
# au centre de ce cadre : elle garde ses proportions, entourée de fond gris.
# Le bandeau de vignettes et la grande image restent donc alignés quel que soit
# le format des sources.
FRAME = (4, 3)
THUMB_W = 480   # largeur de la vignette (360 de haut, en 4:3)
LARGE_W = 2000  # largeur de la grande image (1500 de haut, en 4:3)

# Marge autour de la photo — gris neutre uni #AEAEAE (retour client 2026-11-12 :
# « margin color should be #aeaeae »). Plus de dégradé : les images portent
# cette couleur plate, le CSS n'ajoute que l'ombre. Même cadre à toutes les
# tailles, et pas de dégradé figé dans un fichier WebP. La constante est
# utilisée pour invalider les fichiers déjà générés (cf. EMPREINTE).
TEXTURE = (174, 174, 174)  # #AEAEAE

MIN_OUTPUT = 320   # sous cette taille, la mise en page n'a plus de sens
MIN_QUALITY = 60   # plancher de la qualité adaptative
# poids cible : les scans à grain dépassent facilement 500 Ko à q78 ; la page
# affiche la grande image à ~1000 px de large, ces poids-là ne se voient pas.
LARGE_MAX_BYTES = 250 * 1024
THUMB_MAX_BYTES = 45 * 1024

SOURCE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".psd"}
# fichiers présents dans le répertoire mais non publiables :
SKIP_EXT = {".afphoto", ".pdf"}

IMAGE_MAGICK = shutil.which("magick") or shutil.which("convert")

# marques de contrôle : un dossier de la racine qui en contient n'est pas une
# collection (ex. « _sources », « .git »).
SKIP_DIR_NAMES = {".git", "_sources", ".ds_store", "thumbs"}


# --------------------------------------------------------------------------
# noms de fichiers et de dossiers
# --------------------------------------------------------------------------

def normalize(slug: str) -> str:
    """Identifiant de collection, sans accents : « pti oizo » → « pti-oizo »."""
    s = unicodedata.normalize("NFD", slug)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace("'", "-").replace("’", "-")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "collection"


def sort_key(name: str) -> str:
    """Tri alphabétique à la française : accents repliés, apostrophes et
    espaces ignorés (le nom de collection est toujours affiché tel quel,
    mais « À poil » se classe avec « a », pas après « z »)."""
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^0-9a-z]+", "", s.casefold())


def source_key(path: Path) -> tuple:
    """Tri des images d'une collection : ordre naturel d'après les chiffres du
    nom (« img9 » avant « img10 »), puis alphabétique. Beaucoup de dossiers
    mélangent des noms sans chiffres (« 1900.jpg », « 1870 CDV.jpg ») : on
    retombe alors sur le nom complet."""
    parts = re.split(r"(\d+)", path.stem.casefold())
    key = []
    for i, p in enumerate(parts):
        key.append((0, int(p)) if i % 2 else (1, normalize(p)))
    return (key, path.name.casefold())


# --------------------------------------------------------------------------
# recadrage des bords blancs / unis
# --------------------------------------------------------------------------
#
# Les sources sont des scans : photo sur papier blanc, tirage posé sur un fond
# caramel, négatif sur passe-partout… Le bord utile est le rectangle de pixels
# qui diffèrent du fond *relié au bord de l'image* — c'est ce qu'un humain
# découpe. On le mesure ligne par ligne, colonne par colonne :
#
#   • un pixel « fond » est neutre (faible écart entre canaux) ET proche de la
#     couleur de référence (médiane du bord, qui absorbe le grain du papier) ;
#   • une bande (ligne/colonne) est supprimée seulement si TOUS ses pixels sont
#     du fond — une ligne qui garde un centimètre de photographie ne l'est pas ;
#   • le bord de référence est vérifié au centre ET dans les proches bandes
#     suivantes : sur un scan de tirage sur papier blanc (cf. « bébé cadum »),
#     les marges du papier sont blanches aussi au bord du tirage, et on ne
#     déborderait sur la photo qu'après plusieurs dizaines de pixels — la
#     vérification sur une fenêtre de 2 % de la dimension la coupe net ;
#   • garde-fous : jamais plus de MAX_TRIM de chaque côté (un négatif sur fond
#     très clair reste entier), et si le résultat est invraisemblable (trop
#     petit, format de bandeau), on ne recadre pas.

TRIM_TOL = 30          # écart max à la couleur de fond (0-255, par canal)
EDGE_TOL = 34          # idem, contre la référence de fond de la colonne
NEUTRAL_TOL = 36       # écart max entre canaux pour un pixel « neutre »
MAX_TRIM = 0.2         # au plus 20 % retiré de chaque côté
WIN_MIN = 3            # fenêtre de vérification du bord, en pixels (min/max)
WIN_MAX = 40
WIN_FACTOR = 0.5       # fenêtre = 50 % de la marge trouvée, bornée


class Crop:
    """Rectangle source (l, t, r, b) et raison de l'avoir choisi."""

    def __init__(self, box, why):
        self.box = box
        self.why = why

    @property
    def size(self):
        l, t, r, b = self.box
        return r - l, b - t

    def __repr__(self):
        w, h = self.size
        return f"Crop({self.box}, {w}x{h}, {self.why})"


def _pixels(im: Image.Image):
    return im.load()


def _border_reference(im: Image.Image, edge: str):
    """Couleur de fond d'un bord de l'image : médiane des pixels de ce bord.

    Une référence UNIQUE pour les quatre bords ne marche pas : les scans sont
    souvent éclairés de travers (« no comment » : le papier va de #D0D0C8 à
    gauche à #FEFEFE à droite). Chaque bord a donc sa propre référence.

    Deux passes : médiane brute, puis médiane des seuls pixels déjà proches
    d'elle — un liseré de 1 px plus sombre (bord du scan, ombre portée) ne
    doit pas tirer la référence."""
    W, H = im.size
    px = _pixels(im)
    if edge == "top":
        samples = [px[x, 0] for x in range(0, W, max(1, W // 128))]
    elif edge == "bottom":
        samples = [px[x, H - 1] for x in range(0, W, max(1, W // 128))]
    elif edge == "left":
        samples = [px[0, y] for y in range(0, H, max(1, H // 128))]
    else:
        samples = [px[W - 1, y] for y in range(0, H, max(1, H // 128))]

    def median(cols):
        chans = list(zip(*cols))
        return tuple(sorted(c)[len(c) // 2] for c in chans)

    ref = median(samples)
    close = [c for c in samples
             if max(abs(c[0] - ref[0]), abs(c[1] - ref[1]), abs(c[2] - ref[2])) <= TRIM_TOL]
    if len(close) >= len(samples) // 2:
        ref = median(close)
    return ref


def _is_background(c, ref) -> bool:
    if abs(c[0] - c[1]) > NEUTRAL_TOL or abs(c[1] - c[2]) > NEUTRAL_TOL or abs(c[0] - c[2]) > NEUTRAL_TOL:
        return False  # couleur franche : c'est de la photo
    return max(abs(c[0] - ref[0]), abs(c[1] - ref[1]), abs(c[2] - ref[2])) <= TRIM_TOL


def find_content_box(im: Image.Image) -> Crop | None:
    """Rectangle du contenu, bords unis retirés, ou None si rien de net."""
    W, H = im.size
    med = im.filter(ImageFilter.MedianFilter(3))  # grain / poussière
    px = _pixels(med)

    # fenêtre de vérification : quand on croit avoir trouvé le bord, on exige
    # que les `win` pixels suivants (dans l'image) ne soient pas du fond — sinon
    # le « bord » est encore une marge (papier du tirage, etc.).
    #
    # Largeur de la fenêtre : proportionnelle à la marge trouvée, dans
    # [WIN_MIN, WIN_MAX]. Sur un scan de tirage (cf. « no comment »), la marge
    # du papier fait ~13 px sur 2077 : une fenêtre fixe à 2 % (41 px) ferait
    # échouer la vérification et la marge resterait. À l'inverse, sur un scan
    # où la photo est posée sur du papier blanc (cf. « bébé cadum »), la marge
    # fait des dizaines de pixels et il faut la couper. WIN_MIN = 3 px empêche
    # de confondre le grain d'une marge de 1-2 px avec le bord.
    win_x = win_y = WIN_MIN

    # garde-fou : au plus MAX_TRIM retiré, et toujours assez de place pour que
    # la fenêtre de vérification reste dans l'image.
    max_l = min(int(W * MAX_TRIM), W - win_x - 2)
    max_t = min(int(H * MAX_TRIM), H - win_y - 2)
    if max_l < 1 or max_t < 1:
        return None

    # Recherche par bissection (deux passes) : 1) combien de bandes de fond
    # depuis le bord, en O(log) comparaisons ; 2) ce retrait est-il légitime au
    # regard de la fenêtre ? Coût constant par bord, ce qui rend l'import
    # instantané sur 534 images.
    def trim_edge(edge: str) -> int:
        """Bandes de fond à retirer depuis `edge` ('top'|'bottom'|'left'|'right')."""
        along = "x" if edge in ("top", "bottom") else "y"
        reverse = edge in ("bottom", "right")
        # along_len : longueur des bandes le long du bord ; across_len : nombre
        # de bandes empilées depuis ce bord (la dimension qu'on rogne).
        along_len = W if along == "x" else H
        across_len = H if along == "x" else W
        limit = max_l if along == "x" else max_t
        ref = _border_reference(im, edge)

        # la couleur du fond varie lentement le long du bord (éclairage) : on
        # échantillonne par colonnes, chacune avec SA référence de fond prise
        # dans la bande de bord — une bande est « fond » si chaque colonne
        # correspond à sa propre référence.
        step = max(1, along_len // 200)
        cols = list(range(0, along_len, step))
        refs = {}
        for i in cols:
            # référence de la colonne i : pixel de bord de cette colonne
            if edge in ("top", "bottom"):
                y = 0 if edge == "top" else H - 1
                refs[i] = px[i, y]
            else:
                x = 0 if edge == "left" else W - 1
                refs[i] = px[x, i]

        def is_bg(i, k) -> bool:
            fixed = across_len - 1 - k if reverse else k
            c = px[i, fixed] if along == "x" else px[fixed, i]
            r = refs[i]
            if abs(c[0] - c[1]) > NEUTRAL_TOL or abs(c[1] - c[2]) > NEUTRAL_TOL \
                    or abs(c[0] - c[2]) > NEUTRAL_TOL:
                return False  # couleur franche : c'est de la photo
            return max(abs(c[0] - r[0]), abs(c[1] - r[1]), abs(c[2] - r[2])) <= EDGE_TOL

        def all_bg(a, b) -> bool:
            """Les bandes [a, b) sont-elles toutes du fond ?"""
            for k in range(a, b):
                for i in cols:
                    if not is_bg(i, k):
                        return False
            return True

        # frontière : plus grand n tel que les bandes [0, n) soient du fond
        lo, hi = 0, limit + 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if all_bg(0, mid):
                lo = mid
            else:
                hi = mid
        n_bg = lo
        if n_bg == 0:
            return 0
        # on ne retire que si la fenêtre qui suit le retrait contient de la
        # photo : sinon le bord est encore dans une marge unie (papier du
        # tirage, passe-partout), et recadrer mangerait la photographie.
        win = min(WIN_MAX, max(WIN_MIN, int(n_bg * WIN_FACTOR)))
        for k in range(n_bg, min(n_bg + win, across_len)):
            for i in cols:
                if not is_bg(i, k):
                    return n_bg  # de la photo suit → retrait légitime
        return 0  # marge plus épaisse que la fenêtre : on n'y touche pas

    l = trim_edge("left")
    r = trim_edge("right")
    t = trim_edge("top")
    b = trim_edge("bottom")

    box = (l, t, W - r, H - b)
    w, h = box[2] - box[0], box[3] - box[1]
    if w < W * 0.6 or h < H * 0.6 or w < 32 or h < 32:
        return None

    # une photo déjà proche du plein cadre ne mérite pas de recadrage
    if (l, t, r, b) == (0, 0, 0, 0):
        return None
    # on ignore un liseré d'un ou deux pixels (bruit du scan)
    if max(l, r, t, b) <= 2:
        return None
    return Crop(box, f"bords retirés l{l} t{t} r{r} b{b}")


def centered_box(im: Image.Image, ratio: tuple[int, int]) -> Crop:
    """Plus grand rectangle au format demandé, centré."""
    W, H = im.size
    rw, rh = ratio
    if W / H > rw / rh:  # trop large : on rogne les côtés
        w = int(round(H * rw / rh))
        l = (W - w) // 2
        return Crop((l, 0, l + w, H), "centré (format)")
    h = int(round(W * rh / rw))
    t = (H - h) // 2
    return Crop((0, t, W, t + h), "centré (format)")


def choose_crop(im: Image.Image) -> Crop:
    """Recadrage réel appliqué : bords unis retirés, et si le résultat est
    encore loin du format de la page (bandeau), on recadre au centre."""
    found = find_content_box(im)
    box = found.box if found else (0, 0, im.size[0], im.size[1])
    w, h = box[2] - box[0], box[3] - box[1]
    if not found:
        W, H = im.size
        AR_MAX = 1.8
        if max(w, h) / min(w, h) > AR_MAX:
            c = centered_box(im, FRAME)
            return Crop(c.box, "recadrage centré (image en bandeau)")
        return Crop(box, "aucun bord uni — image entière")

    # Si le contenu trouvé est improbable (très allongé), on préfère le centre :
    # le recadrage des bords a pu attraper une bande de photo.
    if max(w, h) / min(w, h) > 2.6:
        c = centered_box(im, FRAME)
        return Crop(c.box, f"{found.why} puis recentré (format improbable)")
    return found


# --------------------------------------------------------------------------
# encodage
# --------------------------------------------------------------------------

def frame_photo(im: Image.Image, ratio: tuple[int, int]) -> Image.Image:
    """Pose la photo, à ses proportions, sur un cadre au format demandé.

    C'est la « texture » du modèle : toutes les vignettes et toutes les grandes
    images ont le même format, la photo est centrée avec une marge de fond
    égale de chaque côté. On ne déforme JAMAIS la photo (étirer un portrait
    dans un cadre 4:3 se voit immédiatement) et on ne la rogne pas non plus
    (elle est déjà cadrée serrée) : elle est simplement posée au centre.

    Le fond est le gris uni TEXTURE (#AEAEAE) ; le CSS ajoute seulement l'ombre."""
    rw, rh = ratio
    fw, fh = im.width, im.height
    if fw / fh > rw / rh:  # photo trop large : le cadre gagne en hauteur
        fh = int(round(fw * rh / rw))
    else:  # photo trop haute : le cadre gagne en largeur
        fw = int(round(fh * rw / rh))

    frame = Image.new("RGB", (fw, fh), TEXTURE)
    frame.paste(im, ((fw - im.width) // 2, (fh - im.height) // 2))
    return frame


def encode(src: Path, crop: Crop, dest: Path, width: int, quality: int,
           max_bytes: int | None = None) -> None:
    """Recadre (PIL) puis encode en WebP (ImageMagick : rééchantillonnage de
    qualité, suppression des métadonnées).

    Budget de poids (`max_bytes`) : quand l'image dépasse, on baisse d'abord la
    qualité, puis — si le plancher ne suffit pas — la résolution.

    Baisse de qualité d'abord : sur la photo ordinaire (papier mat, grain
    d'argent, tirages sépia), la majeure partie du poids est du détail fin qui
    se voit à peine ; 10 points de qualité en moins ne se voient pas sur un
    écran, alors qu'une image plus petite se voit à l'agrandissement.

    Réduction ensuite : quelques rares scans (carte à paillettes, tirage très
    anxieux) pèsent 450 Ko à q60 — le contenu est dense et aucune qualité ne
    les fait descendre. On les rend alors plus petits (1600 px) : ils restent
    nets à la taille d'affichage (la grande image occupe ~1000 px de large) et
    cessent de plomber la page."""
    w, h = crop.size
    ratio = FRAME
    tmpdir = Path(tempfile.mkdtemp(prefix="cpo-"))
    try:
        im = Image.open(src)
        im.draft("RGB", (max(2400, w), max(2400, h)))  # JPEG : décodage réduit
        im = im.convert("RGB").crop(crop.box)
        im = frame_photo(im, ratio)
        pre = tmpdir / "pre.png"
        im.save(pre)  # sans perte : le rééchantillonnage final est ImageMagick
        dest.parent.mkdir(parents=True, exist_ok=True)

        # paliers : (facteur sur la largeur du cadre, qualité)
        steps = [(1.0, quality)]
        q = quality
        while q - 6 >= MIN_QUALITY:
            q -= 6
            steps.append((1.0, q))
        for size in (0.85, 0.7):
            steps.append((size, max(MIN_QUALITY, q)))

        rw, rh = ratio
        for scale, q in steps:
            w_out = int(round(width * scale))
            dims = (w_out, int(round(w_out * rh / rw)))
            cmd = [
                IMAGE_MAGICK, str(pre),
                "-strip",
                "-resize", f"{dims[0]}x{dims[1]}!",
                "-filter", "Lanczos",
                "-quality", str(q),
                "-define", "webp:method=4",
                "-define", "webp:auto-filter=true",
                str(dest),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            if max_bytes is None or dest.stat().st_size <= max_bytes:
                return
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------
# une collection
# --------------------------------------------------------------------------

def collect_sources(folder: Path) -> list[Path]:
    files = []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext in SKIP_EXT:
            continue
        if ext not in SOURCE_EXT:
            continue
        files.append(p)
    return sorted(files, key=source_key)


def process_collection(folder: Path, args, executor) -> dict | None:
    slug = normalize(folder.name)
    src_files = collect_sources(folder)
    if not src_files:
        log(f"  {folder.name} : aucune image, dossier ignoré")
        return None

    out_dir = OUT_ROOT / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    campaign = args.campaign

    jobs = []       # (index, source, thumb_dest, large_dest, crop, stale)
    errors = []
    width = len(str(len(src_files)))
    for i, src in enumerate(src_files, start=1):
        stem = f"{slug}-{i:0{width}d}"
        thumb = out_dir / f"{stem}-thumb.webp"
        large = out_dir / f"{stem}-large.webp"
        stale = (args.force or not fresh(src, thumb, campaign)
                 or not fresh(src, large, campaign))
        crop = None
        if stale:
            try:
                im = Image.open(src)
                im.draft("RGB", (1600, 1600))
                im = im.convert("RGB")
                crop = choose_crop(im)
            except Exception as e:  # fichier illisible : on le signale, on passe
                errors.append((src, e))
                continue
        jobs.append((i, src, thumb, large, crop, stale))

    def run(job):
        _, src, thumb, large, crop, stale = job
        if not stale or args.dry_run:
            return 0
        encode(src, crop, thumb, THUMB_W, args.quality_thumb, THUMB_MAX_BYTES)
        encode(src, crop, large, LARGE_W, args.quality_large, LARGE_MAX_BYTES)
        return 1

    n_done = sum(executor.map(run, jobs))
    n_stale = sum(1 for j in jobs if j[5])

    # fichiers orphelins (image supprimée du répertoire, ou renommage)
    keep = {j[2].name for j in jobs} | {j[3].name for j in jobs}
    if not args.dry_run:
        for p in out_dir.iterdir():
            if p.is_file() and p.name not in keep:
                p.unlink()

    images = []
    for i, src, thumb, large, crop, stale in jobs:
        images.append({
            "thumb": f"{slug}/{thumb.name}",
            "large": f"{slug}/{large.name}",
            "source": src.name,
            "aspect": aspect_of(crop, thumb),
        })

    n_todo = n_stale if args.dry_run else n_done
    log(f"  {folder.name} → {slug} : {len(images)} images"
        f"{' (nouvelles : %d)' % n_todo if n_todo else ' (à jour)'}")
    for src, e in errors:
        log(f"    ! {src.name} : {e}")

    return {
        "slug": slug,
        "name": folder.name,
        "count": len(images),
        "source_dir": folder.name,
        "images": images,
    }


def aspect_of(crop, dest: Path) -> str:
    """Orientation de la sortie. Toutes les images sont maintenant dans le cadre
    4:3 paysage ; le champ reste dans l'index parce que la page s'en sert pour
    réserver la bonne place à l'image (largeur/hauteur) avant son chargement.
    On lit le fichier existant quand l'image n'a pas été recalculée."""
    try:
        with Image.open(dest) as im:
            return "portrait" if im.size[1] > im.size[0] else "paysage"
    except Exception:
        return "paysage"  # cadre 4:3 par défaut


def recipe_stamp() -> str:
    """Empreinte de la recette de cadre (couleur de marge, format, largeurs).
    Écrite à la racine de static/collection/ : quand elle change — une marge
    passée de #B4BBD8 au gris uni #AEAEAE, par exemple — toutes les images
    déjà générées sont considérées comme périmées, sans --force manuel."""
    return f"fond={'#%02X%02X%02X' % TEXTURE} cadre={FRAME} large={LARGE_W} thumb={THUMB_W}"


def stamp_state() -> tuple[str, float] | None:
    """(recette enregistrée, date du dernier changement de recette), ou None
    si aucune empreinte n'a encore été écrite."""
    try:
        text = (OUT_ROOT / STAMP_NAME).read_text().strip()
        return text, (OUT_ROOT / STAMP_NAME).stat().st_mtime
    except OSError:
        return None


def fresh(src: Path, dest: Path, campaign: float | None = None) -> bool:
    """Une sortie est à jour quand elle est plus récente que la source et que la
    dernière modification de la recette de cadre : changer la recette invalide
    donc tout, même les fichiers plus récents que leur source (`campaign` est
    le mtime de l'empreinte, cf. stamp_state())."""
    try:
        if not dest.exists():
            return False
        out_mtime = dest.stat().st_mtime
        if campaign is not None and out_mtime < campaign:
            return False
        return out_mtime >= src.stat().st_mtime
    except OSError:
        return False


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Importe le répertoire de la collection dans static/collection/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("source", nargs="?", default=str(DEFAULT_SRC),
                    help=f"dossier racine (un sous-dossier par collection) ; défaut : {DEFAULT_SRC}")
    ap.add_argument("--only", action="append", metavar="SLUG",
                    help="ne traiter qu'une collection (slug ou nom de dossier)")
    ap.add_argument("--force", action="store_true", help="refaire même les images à jour")
    ap.add_argument("--dry-run", action="store_true", help="n'écrit rien, affiche seulement")
    ap.add_argument("--keep", action="store_true",
                    help="ne pas supprimer les dossiers des collections absentes")
    ap.add_argument("--quality-large", type=int, default=78)
    ap.add_argument("--quality-thumb", type=int, default=72)
    ap.add_argument("--workers", type=int,
                    default=max(2, (os.cpu_count() or 4) - 1))
    args = ap.parse_args()

    if not IMAGE_MAGICK:
        log("erreur : ImageMagick (`magick`) introuvable")
        return 2

    src_root = Path(args.source).expanduser().resolve()
    if not src_root.is_dir():
        log(f"erreur : {src_root} n'est pas un dossier")
        return 2

    only = None
    if args.only:
        only = set()
        for o in args.only:
            only.add(o)
            only.add(normalize(o))

    folders = []
    for p in sorted(src_root.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name in SKIP_DIR_NAMES:
            continue
        if only and p.name not in only and normalize(p.name) not in only:
            continue
        folders.append(p)

    if not folders:
        log("aucune collection à importer")
        return 1

    log(f"répertoire : {src_root}")
    log(f"sortie     : {OUT_ROOT}")
    log(f"{len(folders)} collection(s){' (filtrées)' if only else ''}")

    if not args.dry_run:
        OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Empreinte de recette : quand elle change, on la réécrit AVANT l'encodage.
    # Son mtime devient la date de campagne : toute sortie plus ancienne est
    # périmée (même si elle est plus récente que sa source), donc un simple
    # changement de marge de fond refait toutes les images sans --force.
    state = stamp_state()
    if state is None or state[0] != recipe_stamp():
        if not args.dry_run:
            (OUT_ROOT / STAMP_NAME).write_text(recipe_stamp() + "\n")
            state = stamp_state()
        else:
            # dry-run : la recette va changer, donc tout sera refait
            state = (recipe_stamp(), float("inf"))
    args.campaign = state[1] if state else None

    started = datetime.now(timezone.utc)
    collections = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for folder in folders:
            res = process_collection(folder, args, ex)
            if res:
                collections.append(res)

    collections.sort(key=lambda c: sort_key(c["name"]))

    # collections présentes sur le disque mais absentes de ce passage
    # (filtré par --only) : on garde leur entrée existante
    index_path = OUT_ROOT / "collections.json"
    if args.only:
        for candidate in (index_path, DATA_INDEX):
            if not candidate.exists():
                continue
            try:
                previous = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            seen = {c["slug"] for c in collections}
            collections.extend(c for c in previous.get("collections", [])
                               if c["slug"] not in seen)
            collections.sort(key=lambda c: sort_key(c["name"]))
            break

    if not args.dry_run:
        present = {c["slug"] for c in collections}
        if not args.keep:
            for d in OUT_ROOT.iterdir():
                if d.is_dir() and d.name not in present:
                    log(f"  suppression : {d.name}")
                    shutil.rmtree(d)
        data = {
            "generated": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": str(src_root),
            "total_images": sum(c["count"] for c in collections),
            "collections": collections,
        }
        payload = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
        index_path.write_text(payload, encoding="utf-8")
        # Hugo lit data/collection.json comme site.Data.collection : c'est ce que
        # consomme layouts/partials/galerie.html. static/ ne lui est pas
        # lisible en tant que ressource — on écrit donc l'index aux deux
        # endroits (le site publié sert aussi collections.json à côté des
        # images, pour les vérifications à la main).
        DATA_INDEX.parent.mkdir(parents=True, exist_ok=True)
        DATA_INDEX.write_text(payload, encoding="utf-8")
        log(f"\nindex : {index_path}")
        log(f"        {DATA_INDEX}")
        log(f"{len(collections)} collections · {data['total_images']} images")
    else:
        log("\n(dry-run : rien n'a été écrit)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
