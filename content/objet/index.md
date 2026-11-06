---
title: objet
sansTitre: true
---

<div class="objet-layout">
<div class="objet-col-texte">
<p>Le Centre de la photographie ordinaire abrite la collection « le commun des mortels » : 3 000 000 de photographies de famille, classées en plus de 400 thèmes.</p>
<p>3 000 000 de photographies amateurs et anonymes déploient un immense récit humain, du début de la photographie à nos jours. Le classement en plus de 400 thèmes révèle l'histoire du regard et des pratiques photographiques populaires.</p>
<p>La collection sauvegarde ce patrimoine vernaculaire et œuvre à changer notre rapport aux photographies devenues anonymes.</p>
</div>

<div class="objet-col-image">
<figure class="objet-image-principale">
<picture>
<source srcset="{{< rel "images/bloc_objet.webp" >}}" type="image/webp">
<img src="{{< rel "images/bloc_objet.jpg" >}}" alt="Photographies de la collection « le commun des mortels » — visuel du bicentenaire de la photographie" width="1400" height="1133" loading="eager" decoding="async">
</picture>
</figure>

<ul class="objet-liens">
<li><button type="button" class="objet-lien" data-panneau="panneau-interview" aria-expanded="false" aria-controls="panneau-interview"><span class="objet-lien-puce" aria-hidden="true"></span><span class="objet-lien-texte">interview</span></button></li>
<li><button type="button" class="objet-lien" data-panneau="panneau-collection" aria-expanded="false" aria-controls="panneau-collection"><span class="objet-lien-puce" aria-hidden="true"></span><span class="objet-lien-texte">la collection</span></button></li>
<li><button type="button" class="objet-lien" data-panneau="panneau-ordinaire" aria-expanded="false" aria-controls="panneau-ordinaire"><span class="objet-lien-puce" aria-hidden="true"></span><span class="objet-lien-texte">l'ordinaire</span></button></li>

</ul>
</div>
</div>

<!-- Les trois « panneaux » sont des <dialog> natifs (cf. components/dialog, v6) :
     fond jaune de la charte, texte noir, positionnés en haut à droite du
     viewport. Le JS en bas de page les ouvre en modal (showModal()) : Échap,
     clic sur le fond et retour du focus au déclencheur sont natifs. -->
<dialog class="objet-dialog" id="panneau-interview" aria-labelledby="panneau-interview-titre">
<div class="objet-dialog-entete">
<h2 class="objet-dialog-titre" id="panneau-interview-titre">vidéo d'interview</h2>
<button type="button" class="objet-dialog-fermer" data-dialog-close aria-label="Fermer">&times;</button>
</div>
<div class="objet-dialog-corps">
<p class="provisoire">vidéo à venir : aucun fichier disponible pour l'instant (bead org-9s8.3)</p>
<figure class="video-ph">
<div class="video-cadre" role="img" aria-label="emplacement de la vidéo d'interview">▶</div>
<figcaption>vidéo d'interview : fichier à recevoir, puis intégré ici (lecture locale, pas de plateforme tierce si possible)</figcaption>
</figure>
</div>
</dialog>

<dialog class="objet-dialog" id="panneau-collection" aria-labelledby="panneau-collection-titre">
<div class="objet-dialog-entete">
<h2 class="objet-dialog-titre" id="panneau-collection-titre">l'histoire de la collection</h2>
<button type="button" class="objet-dialog-fermer" data-dialog-close aria-label="Fermer">&times;</button>
</div>
<div class="objet-dialog-corps">
<p class="provisoire">contenu provisoire : à valider avec le centre (bead org-9s8.3)</p>
<p>La collection naît d'une collection privée, portée par Élise Pic. Elle est aujourd'hui confiée à une association qui œuvre à sa sauvegarde et à sa mise en valeur, et s'ouvre au fonds de donation : les familles peuvent confier leurs photographies pour qu'elles rejoignent le commun des mortels.</p>
<p>La liste des séries : <a href="{{< rel "collection/" >}}">page 4 · collection →</a></p>
<blockquote>Question en attente de réponse du centre (suivi dans le bead org-9s8.8) : faut-il présenter ici la structure administrative du centre (statut, gouvernance, modalités de donation) ?</blockquote>
</div>
</dialog>

<dialog class="objet-dialog" id="panneau-ordinaire" aria-labelledby="panneau-ordinaire-titre">
<div class="objet-dialog-entete">
<h2 class="objet-dialog-titre" id="panneau-ordinaire-titre">le sens de notre travail sur l'ordinaire</h2>
<button type="button" class="objet-dialog-fermer" data-dialog-close aria-label="Fermer">&times;</button>
</div>
<div class="objet-dialog-corps">
<p class="provisoire">contenu provisoire : texte définitif à venir (bead org-9s8.3)</p>
<p>Le « commun des mortels » rassemble des photographies sans auteur connu, prises par et pour des familles. Notre travail consiste à donner leur place à ces images devenues anonymes : les sauvegarder, les classer en thèmes, les exposer.</p>
<p>L'ordinaire photographié (les repas, les fêtes, les vacances, les jardins) est une archive de la vie courante. Le centre s'attache à montrer ce que ces 3 000 000 d'images disent de nous, et à changer notre rapport aux photographies que personne n'a « faites pour l'histoire ».</p>
</div>
</dialog>


<script>
/* objet — trois liens légers ouvrant un <dialog> natif en haut à droite.
   Modèle « components/dialog » : showModal()/close(), ::backdrop, Échap natif.
   Pas de Bootstrap JS sur le site : on reproduit ici l'essentiel du plugin.
   Re-clic sur le lien ouvert = fermeture ; le focus revient au déclencheur. */
(function () {
var liens = Array.prototype.slice.call(document.querySelectorAll('.objet-lien'));

liens.forEach(function (lien) {
var dialog = document.getElementById(lien.dataset.panneau);
if (!dialog) return;

var sync = function () {
var ouvert = dialog.open;
lien.classList.toggle('active', ouvert);
lien.setAttribute('aria-expanded', String(ouvert));
};

/* un modal rend le reste de la page inerte : on ne peut pas cliquer un autre
   lien tant que celui-ci est ouvert, donc pas de bascule directe entre
   panneaux — re-clic impossible aussi, on ferme depuis le dialog. */
lien.addEventListener('click', function () {
if (dialog.open) { dialog.close(); return; }
dialog.showModal();
sync();
});

dialog.addEventListener('close', sync);

/* bouton de fermeture */
dialog.addEventListener('click', function (e) {
if (e.target.closest('[data-dialog-close]')) { dialog.close(); return; }
/* clic sur le fond (::backdrop) : la cible est le <dialog> lui-même */
if (e.target === dialog) {
var r = dialog.getBoundingClientRect();
if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
}
});
});
})();
</script>
