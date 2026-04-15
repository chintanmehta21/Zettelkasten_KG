/* Shared header behavior — back-button + avatar dropdown wiring.
 * Pages opt in by including the rendered header markup (server-side injects via <!--ZK_HEADER--> placeholder).
 * Avatar profile/sign-out logic is intentionally page-owned (Supabase access lives there).
 */
(function () {
  function init() {
    var backBtn = document.querySelector('[data-zk-back]');
    if (backBtn && !backBtn.dataset.zkBound) {
      backBtn.dataset.zkBound = '1';
      backBtn.addEventListener('click', function () {
        if (window.history.length > 1) window.history.back();
        else window.location.href = '/home';
      });
    }

    var avatarBtn = document.getElementById('avatar-btn');
    var avatarDropdown = document.getElementById('avatar-dropdown');
    var avatarWrap = document.getElementById('avatar-wrap');
    if (avatarBtn && avatarDropdown && !avatarBtn.dataset.zkBound) {
      avatarBtn.dataset.zkBound = '1';
      avatarBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        avatarDropdown.classList.toggle('open');
      });
      document.addEventListener('click', function (e) {
        if (avatarWrap && !avatarWrap.contains(e.target)) {
          avatarDropdown.classList.remove('open');
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
