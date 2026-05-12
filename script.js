(function () {
  'use strict';

  const slides = Array.from(document.querySelectorAll('.slide'));
  const progressBar = document.getElementById('progressBar');
  const pageCounter = document.getElementById('pageCounter');
  const btnPrev = document.getElementById('btnPrev');
  const btnNext = document.getElementById('btnNext');
  const btnFullscreen = document.getElementById('btnFullscreen');
  const slideshow = document.getElementById('slideshow');

  const total = slides.length;
  let current = 0;
  let animating = false;

  function goTo(index) {
    if (animating || index === current) return;
    if (index < 0 || index >= total) return;

    animating = true;
    const prev = current;
    current = index;

    // Mark the outgoing slide
    slides[prev].classList.add('leave-left');
    slides[prev].classList.remove('active');

    // Bring in the incoming slide
    slides[current].classList.add('active');

    // Clean up after transition
    const duration = 500;
    setTimeout(() => {
      slides[prev].classList.remove('leave-left');
      animating = false;
    }, duration);

    updateUI();
  }

  function updateUI() {
    progressBar.style.width = total > 1
      ? ((current / (total - 1)) * 100) + '%'
      : '100%';

    pageCounter.textContent = (current + 1) + ' / ' + total;
    btnPrev.disabled = current === 0;
    btnNext.disabled = current === total - 1;
  }

  function next() { goTo(current + 1); }
  function prev() { goTo(current - 1); }

  // Button clicks
  btnNext.addEventListener('click', next);
  btnPrev.addEventListener('click', prev);

  // Keyboard navigation
  document.addEventListener('keydown', function (e) {
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
      case ' ':
        e.preventDefault();
        next();
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        prev();
        break;
      case 'Home':
        goTo(0);
        break;
      case 'End':
        goTo(total - 1);
        break;
      case 'f':
      case 'F':
        toggleFullscreen();
        break;
    }
  });

  // Touch / swipe support
  let touchStartX = 0;
  let touchStartY = 0;

  slideshow.addEventListener('touchstart', function (e) {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
  }, { passive: true });

  slideshow.addEventListener('touchend', function (e) {
    const dx = e.changedTouches[0].clientX - touchStartX;
    const dy = e.changedTouches[0].clientY - touchStartY;
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 40) {
      dx < 0 ? next() : prev();
    }
  }, { passive: true });

  // Fullscreen
  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      slideshow.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }

  btnFullscreen.addEventListener('click', toggleFullscreen);

  document.addEventListener('fullscreenchange', function () {
    btnFullscreen.title = document.fullscreenElement ? '退出全屏 (F)' : '全屏 (F)';
    btnFullscreen.innerHTML = document.fullscreenElement ? '&#x2715;' : '&#x26F6;';
  });

  // Init
  slides[0].classList.add('active');
  updateUI();
})();
