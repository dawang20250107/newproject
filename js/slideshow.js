(function () {
  'use strict';
  var slides = Array.from(document.querySelectorAll('.deck .slide'));
  var total = slides.length;
  var cur = 0, busy = false;
  var ANIM = 620;

  var btnP    = document.getElementById('btnP');
  var btnN    = document.getElementById('btnN');
  var btnF    = document.getElementById('btnF');
  var counter = document.getElementById('counter');
  var bar     = document.getElementById('bar');

  function go(idx) {
    if (busy || idx === cur || idx < 0 || idx >= total) return;
    busy = true;
    slides[cur].classList.add('is-out');
    slides[cur].classList.remove('is-active');
    cur = idx;
    slides[cur].classList.add('is-active');
    setTimeout(function () {
      slides.forEach(function (s) { s.classList.remove('is-out'); });
      busy = false;
    }, ANIM);
    sync();
  }

  function sync() {
    bar.style.width = total > 1 ? (cur / (total - 1) * 100) + '%' : '100%';
    counter.textContent = (cur + 1) + ' / ' + total;
    btnP.disabled = cur === 0;
    btnN.disabled = cur === total - 1;
  }

  btnP.addEventListener('click', function () { go(cur - 1); });
  btnN.addEventListener('click', function () { go(cur + 1); });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') {
      e.preventDefault(); go(cur + 1);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault(); go(cur - 1);
    } else if (e.key === 'Home') {
      go(0);
    } else if (e.key === 'End') {
      go(total - 1);
    } else if (e.key.toLowerCase() === 'f') {
      toggleFS();
    }
  });

  var tx = 0;
  var deck = document.querySelector('.deck');
  deck.addEventListener('touchstart', function (e) {
    tx = e.touches[0].clientX;
  }, { passive: true });
  deck.addEventListener('touchend', function (e) {
    var dx = e.changedTouches[0].clientX - tx;
    if (Math.abs(dx) > 48) go(cur + (dx < 0 ? 1 : -1));
  }, { passive: true });

  function toggleFS() {
    if (!document.fullscreenElement) {
      (document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen)
        .call(document.documentElement);
    } else {
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    }
  }
  btnF.addEventListener('click', toggleFS);
  document.addEventListener('fullscreenchange', function () {
    btnF.textContent = document.fullscreenElement ? '×' : '⛶';
  });

  slides[0].classList.add('is-active');
  sync();
}());
