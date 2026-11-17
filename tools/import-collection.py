#!/usr/bin/env python3
"""
import-collection.py — importe le répertoire de la collection « le commun des
mortels » dans le site.

   usage : tools/import-collection.py [options] [DOSSIER_SOURCE]

   DOSSIER_SOURCE : racine du répertoire ; un sous-dossier par collection.
                    défaut : /home/alx/org/projects/professional/commundesmortels/répertoire/

Pour chaque image source, la photo est publiée ENTIÈRE (aucun recadrage), à ses
proportions, posée sur un cadre de gris uni #AEAEAE qui lui ajoute une marge :

  • gauche/droite : max(2 % de la largeur du cadre, 24 px) ;
  • haut/bas      : max(1,5 % de la largeur de la photo, 20 px).

Le cadre suit donc le format de la photo (un portrait reste un portrait) : il
n'est plus imposé en 4:3. L'index publie la largeur et la hauteur réelles de
chaque sortie, ce qui permet à la page de réserver la bonne place avant
chargement et de composer un srcset.

Chaque photo est écrite en quatre largeurs WebP (srcset) :
     <slug>/<slug>-NN-480.webp     bandeau de vignettes
     <slug>/<slug>-NN-960.webp     mobile / petite fenêtre
     <slug>/<slug>-NN-1440.webp    bureau
     <slug>/<slug>-NN-2000.webp    grande image (écran HiDPI)

Le suffixe est la largeur du CADRE (photo + marges), pas celle de la photo :
c'est la seule valeur utilisable dans un srcset, puisque le fichier est de
cette largeur-là.

Puis écrit l'index lu par la page :
        static/collection/collections.json   (+ copie data/collection.json)

Le script est idempotent : une image est sautée quand toutes ses sorties sont
plus récentes que la source (option --force pour tout refaire). Les collections
disparues du répertoire sont retirées de static/collection/ (option --keep pour
les conserver).

Options
  --only SLUG      ne traiter qu'une collection (répétable) ; slug = nom du
                   dossier normalisé (ex. « pti-oizo »)
  --force          refaire même les images déjà à jour
  --dry-run        afficher ce qui serait fait, sans rien écrire
  --keep           ne pas supprimer les dossiers de collections absentes
  --quality-large  qualité WebP de la plus grande sortie (défaut 78)
  --quality-thumb  qualité WebP de la vignette 480 (défaut 72)
  --workers N      encodages ImageMagick en parallèle (défaut : CPU - 1)

Dépendances : Python 3 + Pillow, ImageMagick 7 (`magick`, encodage et
rééchantillonnage de qualité).

Historique des recettes (cf. recipe_stamp()) :
  • 2026-11-09 → 2026-11-17 : recadrage des bords blancs/unis, cadre 4:3 fixe,
    deux sorties (-thumb 480x360, -large 2000x1500) ;
  • depuis 2026-11-17 (retour client) : plus de recadrage, cadre au format de
    la photo + marges grises G/D haut/bas, quatre sorties pour le srcset.
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

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent  # website-draft/
# Source de vérité UNIQUE du répertoire (décision client 2026-11-17).
# L'ancien /home/alx/code/centre-de-la-photographie-ordinaire/répertoire/ a été
# archivé puis supprimé : ses images ne doivent pas être utilisées.
DEFAULT_SRC = Path(
    "/home/alx/org/projects/professional/commundesmortels/répertoire"
)
OUT_ROOT = ROOT / "static" / "collection"
# empreinte de la recette de cadre (cf. fresh()) : sert seulement à invalider
# les images déjà générées quand la recette change.
STAMP_NAME = "recette.txt"
# Hugo lit data/collection.json comme site.Data.collection (cf.
# layouts/partials/galerie.html) : l'index y est écrit en plus de celui de
# static/collection/.
DATA_INDEX = ROOT / "data" / "collection.json"

# Largeurs du srcset, en largeur de CADRE pour les photos paysage et carrées.
#
# ATTENTION : pour un portrait, la valeur est le GRAND côté (la hauteur), pas la
# largeur. Le cadre suit le format de la photo depuis le 2026-11-17 : un
# portrait en 2000 px de large ferait 3200 px de haut, soit 6,3 Mpx pour une
# photo qui en occupe 1,1 — trois fois le poids de l'ancien cadre 4:3, pour un
# détail que personne ne voit. En bornant le GRAND côté, « 2000 » veut dire la
# même chose dans les deux sens : 2000 px de haut pour un portrait, 2000 px de
# large pour un paysage.
WIDTHS = (480, 960, 1440, 2000)
THUMB_W = WIDTHS[0]
LARGE_W = WIDTHS[-1]

# Marges du cadre — gris neutre uni #AEAEAE (retour client 2026-11-12 : « margin
# color should be #aeaeae »). Les marges sont calculées sur la largeur du cadre
# et converties en pixels entiers ; elles sont donc plus épaisses en valeur
# absolue sur la grande image que sur la vignette, à proportion égale.
# Retour client 2026-11-17 : « add small top/bottom margins », d'où le
# supplément vertical qui n'existait pas avant (le cadre 4:3 collait la photo
# en haut et en bas dès qu'elle était en paysage).
TEXTURE = (174, 174, 174)  # #AEAEAE
MARGIN_X_RATIO = 0.02   # 2 % de la largeur du cadre, de chaque côté
MARGIN_X_MIN = 24       # plancher en pixels, sur la plus grande sortie
MARGIN_Y_RATIO = 0.015  # 1,5 % de la largeur de la photo, en haut et en bas
MARGIN_Y_MIN = 20       # plancher en pixels, sur la plus grande sortie

MIN_QUALITY = 60   # plancher de la qualité adaptative
# Budget de poids par palier, en octets. Le srcset évite de servir du 2000 px
# sur mobile ; ces budgets bornent ce que coûte le pire cas (desktop HiDPI).
MAX_BYTES = {
    480: 45 * 1024,
    960: 110 * 1024,
    1440: 190 * 1024,
    2000: 250 * 1024,
}
# sous ce rapport, une image est un bandeau : on la garde telle quelle (plus de
# recadrage automatique), mais on la signale dans le compte rendu.
SKINNY_AR = 3.0

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
# cadre : la photo entière + marges grises
# --------------------------------------------------------------------------
#
# Le recadrage des bords blancs / unis a été retiré le 2026-11-17 (décision
# client) : la photo est publiée telle quelle, y compris les marges du papier
# du scan ou du passe-partout quand il y en a. C'est un choix assumé — le
# cadrage serré manuel se fait en amont, dans le répertoire.
#
# Ce qui reste à calculer, c'est le cadre : la taille de sortie pour une
# largeur de cadre donnée, et la position de la photo dedans.

def margin_px(frame_w: int, photo_w_ratio: float) -> tuple[int, int]:
    """Marges (x, y) en pixels pour un cadre de largeur `frame_w`.

    Les planchers (MARGIN_X_MIN, MARGIN_Y_MIN) sont donnés pour la plus grande
    sortie et passent à l'échelle en dessous, sinon les marges d'une vignette
    de 480 px mangeraient un dixième de l'image."""
    scale = frame_w / LARGE_W
    mx = max(round(MARGIN_X_RATIO * frame_w), round(MARGIN_X_MIN * scale)) or 1
    my = max(round(MARGIN_Y_RATIO * frame_w * photo_w_ratio),
             round(MARGIN_Y_MIN * scale)) or 1
    return mx, my


def frame_dims(im: Image.Image, frame_w: int) -> tuple[int, int, int, int]:
    """Dimensions du cadre et marges pour une photo, au grand côté demandé.

    Retourne (largeur, hauteur, marge_x, marge_y). La photo garde ses
    proportions exactes ; le cadre est la photo + les marges. Le format du
    cadre suit donc celui de la photo.

    `frame_w` est le GRAND côté du cadre : la largeur pour un paysage, la
    hauteur pour un portrait (cf. WIDTHS). C'est ce qui garde un poids
    comparable entre les deux orientations."""
    photo_ratio = im.height / im.width
    is_portrait = photo_ratio > 1
    # largeur nominale du cadre : pour un portrait, on la déduit de la hauteur
    # voulue, une fois les marges connues (elles sont proportionnelles, on les
    # estime sur la largeur nominale puis on les recalcule).
    frame_w = frame_w
    if is_portrait:
        mx, my = margin_px(frame_w, photo_ratio)
        photo_h = frame_w - 2 * my
        frame_w = max(WIDTHS[0], round(photo_h / photo_ratio) + 2 * mx)
    mx, my = margin_px(frame_w, photo_ratio)
    photo_w = frame_w - 2 * mx
    photo_h = max(1, round(photo_w * photo_ratio))
    return frame_w, photo_h + 2 * my, mx, my


def frame_photo(im: Image.Image, frame_w: int) -> Image.Image:
    """Pose la photo, à ses proportions, au centre d'un cadre gris.

    On ne déforme JAMAIS la photo (étirer un portrait se voit immédiatement) et
    on ne la rogne pas : elle est simplement posée au centre, sur le gris uni
    TEXTURE (#AEAEAE). Le CSS ajoute seulement l'ombre."""
    fw, fh, mx, my = frame_dims(im, frame_w)
    if im.width != fw - 2 * mx or im.height != fh - 2 * my:
        im = im.resize((fw - 2 * mx, fh - 2 * my), Image.LANCZOS)
    frame = Image.new("RGB", (fw, fh), TEXTURE)
    frame.paste(im, (mx, my))
    return frame


# --------------------------------------------------------------------------
# encodage
# --------------------------------------------------------------------------

def encode_sizes(src: Path, sizes: tuple[int, ...], quality: int,
                 quality_thumb: int, dests: dict[int, Path]) -> dict[int, tuple[int, int]]:
    """Écrit les sorties WebP d'une photo et retourne {largeur: (w, h)}.

    Une seule ouverture du fichier source et un seul cadre plein format, puis
    chaque palier est rééchantillonné par ImageMagick (Lanczos, métadonnées
    retirées). Le cadre est construit à la plus grande largeur demandée : les
    paliers suivants n'en sont qu'une réduction, ce qui garde des marges
    proportionnelles partout.

    Budget de poids : quand un palier dépasse, on baisse d'abord la qualité
    (10 points de moins ne se voient pas sur un écran, une image plus petite se
    voit à l'agrandissement), puis on se contente du plancher MIN_QUALITY — la
    largeur, elle, est fixée par le srcset et ne bouge pas.
    """
    biggest = max(sizes)
    tmpdir = Path(tempfile.mkdtemp(prefix="cpo-"))
    out = {}
    try:
        im = Image.open(src)
        im.draft("RGB", (biggest * 2, biggest * 2))  # JPEG : décodage réduit
        im = im.convert("RGB")
        seen = (im.width, im.height)
        frame = frame_photo(im, biggest)
        pre = tmpdir / "pre.png"
        frame.save(pre)  # sans perte : le rééchantillonnage final est IM
        fw, fh = frame.size

        for w in sizes:
            dest = dests[w]
            dest.parent.mkdir(parents=True, exist_ok=True)
            # grand côté : la largeur pour un cadre paysage, la hauteur pour un
            # portrait (cf. WIDTHS et frame_dims).
            if fh > fw:
                h = w
                out_w = max(1, round(fw * w / fh))
            else:
                out_w = w
                h = max(1, round(fh * w / fw))
            q0 = quality_thumb if w == THUMB_W else quality
            budget = MAX_BYTES.get(w)
            steps = [q0]
            q = q0
            while q - 6 >= MIN_QUALITY:
                q -= 6
                steps.append(q)
            for q in steps:
                cmd = [
                    IMAGE_MAGICK, str(pre),
                    "-strip",
                    "-resize", f"{out_w}x{h}!",
                    "-filter", "Lanczos",
                    "-quality", str(q),
                    "-define", "webp:method=4",
                    "-define", "webp:auto-filter=true",
                    str(dest),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                if budget is None or dest.stat().st_size <= budget:
                    break
            out[w] = (out_w, h)
        out["source"] = seen
        return out
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


def output_paths(out_dir: Path, stem: str) -> dict[int, Path]:
    return {w: out_dir / f"{stem}-{w}.webp" for w in WIDTHS}


def process_collection(folder: Path, args, executor) -> dict | None:
    slug = normalize(folder.name)
    src_files = collect_sources(folder)
    if not src_files:
        log(f"  {folder.name} : aucune image, dossier ignoré")
        return None

    out_dir = OUT_ROOT / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    campaign = args.campaign

    jobs = []       # (index, source, dests, stale)
    errors = []
    width = len(str(len(src_files)))
    for i, src in enumerate(src_files, start=1):
        stem = f"{slug}-{i:0{width}d}"
        dests = output_paths(out_dir, stem)
        stale = args.force or not all(fresh(src, d, campaign) for d in dests.values())
        jobs.append((i, src, dests, stale))

    def run(job):
        idx, src, dests, stale = job
        if not stale or args.dry_run:
            return 0
        try:
            encode_sizes(src, WIDTHS, args.quality_large, args.quality_thumb, dests)
            return 1
        except Exception as e:  # fichier illisible : on le signale, on passe
            errors.append((src, e))
            return 0

    n_done = sum(executor.map(run, jobs))
    n_stale = sum(1 for j in jobs if j[3])

    # fichiers orphelins (image supprimée du répertoire, renommage, ou ancienne
    # recette -thumb/-large)
    keep = {d.name for j in jobs for d in j[2].values()}
    keep.add(STAMP_NAME)
    if not args.dry_run:
        for p in out_dir.iterdir():
            if p.is_file() and p.name not in keep:
                p.unlink()

    images = []
    skinny = []
    for idx, src, dests, stale in jobs:
        entry = {
            "source": src.name,
            "sources": [
                {"w": w, "file": f"{slug}/{dests[w].name}"} for w in WIDTHS
            ],
        }
        # largeur / hauteur réelles de la plus grande sortie : la page s'en sert
        # pour réserver la place avant chargement (ratio variable désormais).
        big = dests[LARGE_W]
        try:
            with Image.open(big) as im:
                w, h = im.size
            entry.update({"w": w, "h": h})
            # raccourcis pratiques : `thumb` pour le bandeau, `large` pour le
            # lien (l'image ouverte en grand). Le srcset se sert de `sources`.
            entry["thumb"] = f"{slug}/{dests[THUMB_W].name}"
            entry["large"] = f"{slug}/{big.name}"
            if max(w, h) / min(w, h) > SKINNY_AR:
                skinny.append(src.name)
        except Exception:
            entry.update({"w": LARGE_W, "h": round(LARGE_W * 3 / 4)})
            entry["thumb"] = f"{slug}/{dests[THUMB_W].name}"
            entry["large"] = f"{slug}/{big.name}"
        images.append(entry)

    n_todo = n_stale if args.dry_run else n_done
    log(f"  {folder.name} → {slug} : {len(images)} images"
        f"{' (nouvelles : %d)' % n_todo if n_todo else ' (à jour)'}")
    for src, e in errors:
        log(f"    ! {src.name} : {e}")
    if skinny:
        log(f"    · images en bandeau (tout en largeur, gardées entières) : "
            f"{', '.join(skinny[:6])}{' …' if len(skinny) > 6 else ''}")

    return {
        "slug": slug,
        "name": folder.name,
        "count": len(images),
        "source_dir": folder.name,
        "images": images,
    }


def recipe_stamp() -> str:
    """Empreinte de la recette de cadre. Écrite à la racine de static/collection/ :
    quand elle change, toutes les images déjà générées sont considérées comme
    périmées, sans --force manuel."""
    return (
        f"fond={'#%02X%02X%02X' % TEXTURE} "
        f"marges=x{MARGIN_X_RATIO}/{MARGIN_X_MIN}px,y{MARGIN_Y_RATIO}/{MARGIN_Y_MIN}px "
        f"ratio=photo largeurs={'-'.join(map(str, WIDTHS))}"
    )


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
            "widths": list(WIDTHS),
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
