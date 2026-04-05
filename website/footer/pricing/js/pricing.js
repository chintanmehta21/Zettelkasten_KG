(function () {
  'use strict';

  var tabButtons = Array.prototype.slice.call(document.querySelectorAll('.pricing-tab'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.pricing-panel'));
  if (!tabButtons.length || !panels.length) return;

  function setActive(tabName) {
    tabButtons.forEach(function (btn) {
      var active = btn.getAttribute('data-tab') === tabName;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    panels.forEach(function (panel) {
      var id = panel.id === 'subscription-panel' ? 'subscription' : 'adhoc';
      panel.classList.toggle('is-active', id === tabName);
    });
  }

  tabButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      setActive(button.getAttribute('data-tab'));
    });
  });
})();

