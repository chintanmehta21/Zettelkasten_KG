// avatar.js — shared avatar renderer for mobile + desktop.
// Reads /api/profile (logged-in) or falls back to the anon Zoro avatar.
// Exposes window.ZK.renderAvatar(target, opts).

(function () {
  "use strict";

  const ZORO_AVATAR = "/artifacts/avatars/avatar_00.svg";
  const ALL_AVATARS = Array.from({ length: 60 }, (_, i) =>
    `/artifacts/avatars/avatar_${String(i).padStart(2, "0")}.svg`
  );

  async function fetchProfile() {
    try {
      const r = await fetch("/api/profile", { credentials: "include" });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  /**
   * @param {HTMLElement} target — element to receive the rendered avatar
   * @param {{ size?: number, anon?: boolean }} opts
   */
  async function renderAvatar(target, opts = {}) {
    if (!target) return;
    const size = opts.size || 38;
    let url = ZORO_AVATAR;
    if (!opts.anon) {
      const prof = await fetchProfile();
      if (prof && prof.avatar_url) url = prof.avatar_url;
    }
    target.innerHTML =
      `<img class="zk-avatar-img" src="${url}" width="${size}" height="${size}" alt="" loading="lazy">`;
  }

  function avatarUrls() {
    return ALL_AVATARS.slice();
  }

  window.ZK = window.ZK || {};
  window.ZK.renderAvatar = renderAvatar;
  window.ZK.avatarUrls = avatarUrls;
})();
