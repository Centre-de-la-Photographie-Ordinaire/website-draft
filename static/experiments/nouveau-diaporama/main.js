(function () {
  'use strict';

  var IMAGES_JSON = 'images.json';
  var images = [];
  var currentIndex = 0;
  var filmstrip = document.getElementById('filmstrip');
  var btnPrev = document.getElementById('btn-prev');
  var btnNext = document.getElementById('btn-next');
  var busy = false;

  var TRANSITION = 'transform 0.5s cubic-bezier(0.25, 0.1, 0.25, 1)';

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    return arr;
  }

  // Calcule translateX pour centrer l'image a targetIdx
  function centerOn(targetIdx) {
    var imgs = filmstrip.children;
    if (!imgs.length) return;
    var offset = 0;
    for (var i = 0; i < targetIdx && i < imgs.length; i++) {
      offset += imgs[i].offsetWidth;
    }
    var vw = window.innerWidth;
    var w = imgs[targetIdx] ? imgs[targetIdx].offsetWidth : 0;
    filmstrip.style.transform = 'translateX(' + ((vw - w) / 2 - offset) + 'px)';
  }

  function build(srcs, centerIdx) {
    var frag = document.createDocumentFragment();
    srcs.forEach(function (src) {
      var img = document.createElement('img');
      img.src = src;
      img.alt = '';
      img.draggable = false;
      img.decoding = 'async';
      frag.appendChild(img);
    });
    filmstrip.replaceChildren(frag);
    requestAnimationFrame(function () {
      centerOn(centerIdx);
    });
  }

  function showSteady() {
    if (busy) return;
    var total = images.length;
    var srcs = [ -2, -1, 0, 1, 2 ].map(function (d) {
      return images[(currentIndex + d + total) % total];
    });
    filmstrip.style.transition = 'none';
    build(srcs, 2);
  }

  function animateSlide(srcs, startIdx, endIdx, newIdx) {
    busy = true;
    var frag = document.createDocumentFragment();
    srcs.forEach(function (src) {
      var img = document.createElement('img');
      img.src = src;
      img.alt = '';
      img.draggable = false;
      img.decoding = 'async';
      frag.appendChild(img);
    });
    filmstrip.replaceChildren(frag);

    requestAnimationFrame(function () {
      // Frame 1: position de depart, pas de transition
      filmstrip.style.transition = 'none';
      centerOn(startIdx);
      // Force le reflow pour que le navigateur enregistre la position de depart
      void filmstrip.offsetHeight;

      // Frame 1 (suite): transition + position d'arrivee
      filmstrip.style.transition = TRANSITION;
      centerOn(endIdx);

      filmstrip.addEventListener('transitionend', function f() {
        currentIndex = newIdx;
        busy = false;
        showSteady();
        filmstrip.removeEventListener('transitionend', f);
      }, { once: true });
    });
  }

  function slideNext() {
    if (busy || !images.length) return;
    var total = images.length;
    var nIdx = (currentIndex + 1) % total;
    var srcs = [
      images[(currentIndex - 1 + total) % total],
      images[currentIndex],
      images[nIdx],
      images[(nIdx + 1) % total],
      images[(nIdx + 2) % total]
    ];
    animateSlide(srcs, 1, 2, nIdx);
  }

  function slidePrev() {
    if (busy || !images.length) return;
    var total = images.length;
    var pIdx = (currentIndex - 1 + total) % total;
    var srcs = [
      images[(pIdx - 2 + total) % total],
      images[(pIdx - 1 + total) % total],
      images[pIdx],
      images[currentIndex],
      images[(currentIndex + 1) % total]
    ];
    animateSlide(srcs, 3, 2, pIdx);
  }

  function start() {
    if (!images.length) return;
    currentIndex = images.length > 5 ? 3 : 0;
    // Precharger les 5 premieres images avant d'afficher quoi que ce soit.
    var total = images.length;
    var srcs = [ -2, -1, 0, 1, 2 ].map(function (d) {
      return images[(currentIndex + d + total) % total];
    });
    var loaded = 0;
    srcs.forEach(function (src) {
      var img = new Image();
      img.onload = function () {
        loaded++;
        if (loaded >= srcs.length) {
          // Toutes les images sont dans le cache navigateur -> showSteady
          showSteady();
        }
      };
      img.onerror = function () {
        loaded++;
        if (loaded >= srcs.length) showSteady();
      };
      img.src = src;
    });
    // Securite si les images sont deja en cache (onload deja declenche)
    if (loaded >= srcs.length) showSteady();
  }

  function loadImages() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', IMAGES_JSON + '?t=' + Date.now(), true);
    xhr.onload = function () {
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          if (Array.isArray(data)) images = shuffle(data);
          else if (data.images) images = shuffle(data.images);
          start();
        } catch (e) { fallbackScan(); }
      } else { fallbackScan(); }
    };
    xhr.onerror = fallbackScan;
    xhr.send();
  }

  function fallbackScan() {
    var base = '../diaporama/images/';
    images = shuffle([
      '20250804_185251.jpg',
      '20241106_080230.jpg',
      '20241024_120525.jpg'
    ].map(function (n) { return base + n; }));
    start();
  }

  if (btnPrev) btnPrev.addEventListener('click', slidePrev);
  if (btnNext) btnNext.addEventListener('click', slideNext);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight') slideNext();
    else if (e.key === 'ArrowLeft') slidePrev();
  });
  window.addEventListener('resize', function () {
    if (!busy && filmstrip.children.length) {
      filmstrip.style.transition = 'none';
      centerOn(2);
    }
  });
  document.getElementById('stage').addEventListener('contextmenu', function (e) { e.preventDefault(); });

  loadImages();
})();
