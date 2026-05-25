// profile.js — mobile profile page: auth + unauth states + avatar picker (T11).
// Reuses the existing OAuth modal via #m-avatar-btn click in unauth state.

(function () {
  "use strict";

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function hasSession() {
    return document.cookie.split(';').some(c => {
      const name = c.trim().split('=')[0];
      return name === 'sb-access-token' || (name.startsWith('sb-') && name.endsWith('-auth-token'));
    });
  }

  async function loadProfile() {
    try {
      const r = await fetch('/api/profile', { credentials: 'include' });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  async function patchProfile(avatar_url) {
    const r = await fetch('/api/profile', {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar_url }),
    });
    if (!r.ok) throw new Error('patch failed: ' + r.status);
    return await r.json();
  }

  function renderUnauth() {
    document.getElementById('profile-unauth').hidden = false;
    document.getElementById('profile-auth').hidden = true;

    const btn = document.getElementById('profile-signin-btn');
    btn.addEventListener('click', () => {
      // Programmatically open the existing OAuth modal via the avatar header button.
      const avatarBtn = document.getElementById('m-avatar-btn');
      if (avatarBtn) avatarBtn.click();
    });
  }

  function renderAuth(profile) {
    document.getElementById('profile-unauth').hidden = true;
    document.getElementById('profile-auth').hidden = false;
    document.getElementById('profile-email').textContent = profile.email || '';

    const avatarSlot = document.getElementById('profile-avatar');
    const currentUrl = profile.avatar_url || '/artifacts/avatars/avatar_00.svg';
    avatarSlot.innerHTML =
      '<img src="' + escHtml(currentUrl) + '" width="72" height="72" alt="" class="zk-avatar-img">';

    renderPicker(currentUrl);

    document.getElementById('profile-signout').addEventListener('click', signOut);
  }

  function renderPicker(currentUrl) {
    const picker = document.getElementById('avatar-picker');
    const urls = (window.ZK && window.ZK.avatarUrls) ? window.ZK.avatarUrls() : [];
    if (!urls.length) return;

    const io = ('IntersectionObserver' in window) ? new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          const img = e.target.querySelector('img');
          if (img && img.dataset.src && !img.src) img.src = img.dataset.src;
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: '80px' }) : null;

    urls.forEach(url => {
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'm-avatar-cell' + (url === currentUrl ? ' is-selected' : '');
      cell.dataset.url = url;
      cell.setAttribute('aria-label', 'Pick avatar ' + url.replace(/^.*avatar_/, '').replace(/\.svg$/, ''));
      cell.innerHTML = '<img data-src="' + escHtml(url) + '" width="56" height="56" alt="">';
      cell.addEventListener('click', () => selectAvatar(url, cell));
      picker.appendChild(cell);
      if (io) io.observe(cell); else {
        // Fallback: load immediately if IntersectionObserver unavailable
        const img = cell.querySelector('img');
        if (img) img.src = img.dataset.src;
      }
    });
  }

  async function selectAvatar(url, cellEl) {
    const prev = document.querySelector('.m-avatar-cell.is-selected');
    if (prev) prev.classList.remove('is-selected');
    cellEl.classList.add('is-selected');
    const avatarSlot = document.getElementById('profile-avatar');
    avatarSlot.innerHTML =
      '<img src="' + escHtml(url) + '" width="72" height="72" alt="" class="zk-avatar-img">';
    try {
      await patchProfile(url);
      // Broadcast so header avatar updates without reload
      document.dispatchEvent(new CustomEvent('zk:avatar-changed', { detail: { url } }));
    } catch (err) {
      console.error(err);
      if (prev) prev.classList.add('is-selected');
      cellEl.classList.remove('is-selected');
      alert('Could not save avatar.');
    }
  }

  async function signOut() {
    try {
      if (window.ZKAuth && typeof window.ZKAuth.signOut === 'function') {
        await window.ZKAuth.signOut();
      } else if (typeof window.signOut === 'function') {
        await window.signOut();
      }
    } catch (err) {
      console.error('sign-out failed:', err);
    }
    location.assign('/m/profile');
  }

  async function init() {
    if (!hasSession()) { renderUnauth(); return; }
    const p = await loadProfile();
    if (!p) { renderUnauth(); return; }
    renderAuth(p);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
