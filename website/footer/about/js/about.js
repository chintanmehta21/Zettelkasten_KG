(function () {
  'use strict';

  var sections = Array.prototype.slice.call(document.querySelectorAll('.about-shell main section'));
  if (!sections.length) return;

  if (!('IntersectionObserver' in window)) {
    sections.forEach(function (s) { s.classList.add('is-visible'); });
    return;
  }

  var obs = new IntersectionObserver(
    function (entries, observer) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.12, rootMargin: '0px 0px -6% 0px' },
  );

  sections.forEach(function (section, idx) {
    section.style.transitionDelay = String(idx * 70) + 'ms';
    obs.observe(section);
  });
})();

