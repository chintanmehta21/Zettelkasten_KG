// avatar.js — shared avatar renderer for mobile + desktop.
//
// Reads /api/me (canonical) with a Bearer token from window.getAuthToken (or
// window.ZKAuth.getSession), validates the returned URL against the curated
// /artifacts/avatars/ set, and renders. Anonymous or any non-curated value
// falls back to the Zoro avatar so a malicious metadata string can never
// reach an <img src=...> via this path.
//
// Exposes:
//   window.ZK.renderAvatar(targetEl, { size?: number, anon?: boolean })
//   window.ZK.avatarUrls()        -> array of all 120 curated paths
//   window.ZK.isCuratedAvatarUrl  -> shared validator (used by profile.js etc.)

(function () {
  "use strict";

  const ZORO_AVATAR = "/artifacts/avatars/avatar_00.svg";
  // Exact bound to the 120 on-disk assets (avatar_00..avatar_119) — mirrors
  // website/app.py::_CURATED_AVATAR_RE. Must stay in sync with that gate.
  const CURATED_RE = /^\/artifacts\/avatars\/avatar_(0\d|[1-9]\d|1[01]\d)\.svg$/;
  const ALL_AVATARS = Array.from({ length: 120 }, (_, i) =>
    `/artifacts/avatars/avatar_${String(i).padStart(2, "0")}.svg`
  );

  function isCuratedAvatarUrl(url) {
    return typeof url === "string" && CURATED_RE.test(url);
  }

  function escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  async function authToken() {
    try {
      if (typeof window.getAuthToken === "function") {
        const t = window.getAuthToken();
        if (t) return t;
      }
      if (window.ZKAuth && typeof window.ZKAuth.getSession === "function") {
        const s = await window.ZKAuth.getSession();
        if (s && s.access_token) return s.access_token;
      }
    } catch (e) { void e; }
    return "";
  }

  async function fetchMe() {
    try {
      const token = await authToken();
      if (!token) return null;
      const r = await fetch("/api/me", {
        credentials: "include",
        headers: { "Authorization": "Bearer " + token },
      });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  /**
   * Render the current user's avatar into `target`.
   *   opts.size  — pixel dimension (default 38)
   *   opts.anon  — skip /api/me call and always render the Zoro fallback
   */
  async function renderAvatar(target, opts = {}) {
    if (!target) return;
    const size = Number(opts.size) > 0 ? Number(opts.size) : 38;
    let url = ZORO_AVATAR;
    if (!opts.anon) {
      const me = await fetchMe();
      if (me && isCuratedAvatarUrl(me.avatar_url)) url = me.avatar_url;
    }
    target.innerHTML =
      `<img class="zk-avatar-img" src="${escHtml(url)}" width="${size}" height="${size}" alt="" loading="lazy">`;
  }

  function avatarUrls() {
    return ALL_AVATARS.slice();
  }

  window.ZK = window.ZK || {};
  window.ZK.renderAvatar = renderAvatar;
  window.ZK.avatarUrls = avatarUrls;
  window.ZK.isCuratedAvatarUrl = isCuratedAvatarUrl;
})();
