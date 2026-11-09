# centre de la photographie ordinaire — brouillons

Squelette Hugo du futur site **centredelaphotographieordinaire.fr**.

Le site sera monté par **expérimentation** : chaque experiment est une page
autonome qui partage la charte graphique du Centre (fond `#2A2E33`, texte
`#F5EFE4`, accent `#FAB617`) mais explore une UX différente. Les éléments qui
fonctionnent alimenteront ensuite le site complet.

## construire

```sh
hugo build          # génère public/
hugo server         # mode dev, auto-reload
```

## ajouter une experiment

1. Créer `static/experiments/<nom>/` avec son `index.html` autonome
   (JS/CSS/images à l'intérieur, chemins relatifs).
2. Ajouter l'entrée dans la liste `## experiments` de `content/_index.md` :

```md
- **<nom>** — [ouvrir] (/experiments/<nom>/)
```

L'URL finale sera `/experiments/<nom>/`. Ne pas créer de page Hugo du même
nom : les fichiers statiques prennent la main.

## collection : importer le répertoire

La page `/collection/` n'est pas écrite à la main : elle est générée depuis le
répertoire de la collection (un sous-dossier par collection, les images à
l'intérieur).

```sh
tools/import-collection.py          # tout le répertoire
tools/import-collection.py --only pti-oizo --force   # une seule collection
tools/import-collection.py --dry-run                 # ce qui serait fait
```

Le script, pour chaque image source :

1. **retire les bords blancs / unis** (papier du scan, passe-partout) — repère
   par bord, robuste aux scans éclairés de travers, avec garde-fous ;
2. **pose la photo sur une marge grise unie `#AEAEAE`** : la photo garde ses
   proportions, centrée dans un cadre 4:3 paysage ;
3. écrit deux **WebP** : vignette `480×360`/`360×480` et grande image
   `2000×1500`/`1500×2000`, avec un budget de poids adaptatif (qualité puis
   résolution : jamais plus de ~250 Ko pour la grande image) ;
4. écrit l'index lu par la page : `data/collection.json` (Hugo le lit comme
   `site.Data.collection`) et `static/collection/collections.json` (copie pour
   inspection).

Le script est **idempotent** : relancer sans option ne retraite que les images
nouvelles ou modifiées (0,4 s quand tout est à jour). Changer la recette de
cadre (la couleur de marge, par exemple) invalide tout automatiquement :
l'empreinte de la recette est écrite dans `static/collection/recette.txt`.
Les collections disparues du répertoire sont retirées du site.

Dépendances : Python 3 + Pillow, ImageMagick 7 (`magick`).

La page est un **accordéon** : une ligne par collection (nom + nombre d'images),
une seule ouverte à la fois, comme avant. Le panneau ouvert contient la
galerie : grande image au-dessus, bandeau de vignettes défilant en dessous
(modèle romapublications). La galerie n'est construite qu'à l'ouverture du
panneau : la page ne télécharge jamais les 532 vignettes d'un coup, seulement
celles de la collection qu'on regarde.

`layouts/partials/galerie.html` (liste + galerie), `static/collection/galerie.js`
(navigation : vignettes, flèches, clavier ←/→, balayage, liens `#collection/N`).
Le formulaire « prochaines parutions » (Formspree) est en bas de page ; son
endpoint se règle dans `hugo.toml` (`params.formspree_collection`).

## panneaux « dialog » (haut-droite, jaune)

Les trois liens de `/objet/` et les liens optionnels au dos des cartes de
`/missions/` ouvrent un `<dialog>` natif en haut à droite du viewport, texte
noir sur fond jaune (modèle `components/dialog`). Le site ne charge pas le JS
Bootstrap : `layouts/partials/dialog-script.html` en reproduit l'essentiel
(`showModal()` / `close()`, `::backdrop`, Échap, retour du focus).

Depuis une page en Markdown, inclure le script avec `{{< dialog-script >}}`,
puis sur le déclencheur :

```html
<a href="#" data-dialog="mon-panneau" aria-expanded="false">ouvrir</a>

<dialog class="objet-dialog" id="mon-panneau" aria-labelledby="mon-panneau-titre">
  <div class="objet-dialog-entete">
    <h2 class="objet-dialog-titre" id="mon-panneau-titre">titre</h2>
    <button type="button" class="objet-dialog-fermer" data-dialog-close aria-label="Fermer">&times;</button>
  </div>
  <div class="objet-dialog-corps"><p>contenu</p></div>
</dialog>
```

Le shortcode `{{< rel "chemin/" >}}` reste à utiliser pour les liens internes
(sous-chemin `/website-draft/`).

> dans les pages en Markdown, utilisez `<!-- -->` et non `{{/* */}}` pour les
> commentaires : selon la version de Hugo, ce dernier s'affiche en clair.

## remotes / deploys

- `origin` — https://github.com/Centre-de-la-Photographie-Ordinaire/website-draft
- `lamai` — http://localhost:3000/alx/website-draft (miroir gitea lamai)

Deploys github pages (deux repos, meme contenu) :

| repo github | sert sur | `HUGO_BASE_URL` (deploy.yml) |
|---|---|---|
| `.../website-draft` | `centre-de-la-photographie-ordinaire.github.io/website-draft/` | `.../website-draft/` |
| `.../centre-de-la-photographie-ordinaire.github.io` (site org) | racine `centre-de-la-photographie-ordinaire.github.io/` | `.../` |

Le push sur `main` de chaque repo declenche son workflow : `hugo build` puis
push force de `public/` vers la branche `gh-pages` du meme repo (token dans le
secret `PAGES_DEPLOY_TOKEN`, configures via `gh secret set`). `static/.nojekyll`
desactive Jekyll sur la branche `gh-pages`.

**Sync** : apres commit sur ce repo (website-draft), re-appliquer le meme commit
sur le repo `.github.io` avec la seule difference `HUGO_BASE_URL` (voir le
dernier commit de chaque repo pour la forme exacte).
