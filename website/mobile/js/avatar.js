// avatar.js — shared avatar renderer for mobile + desktop.
//
// Reads /api/me (canonical) with a Bearer token from window.getAuthToken (or
// window.ZKAuth.getSession) and renders a curated /artifacts/avatars/ image.
// Mirrors desktop header.js resolveAvatarUrl so both surfaces behave identically:
//   server avatar_url (if curated) → localStorage cache → random-assign+persist.
// A no-avatar authed user is assigned a random curated avatar that is persisted
// to the profile (PUT /api/me/avatar) and cached under the SAME key desktop uses,
// so the header shows a real avatar image (not bare initials) and stays identical
// across mobile ⇄ desktop. Only curated URLs ever reach an <img src=…>, so a
// malicious metadata string can never be rendered through this path.
//
// Exposes:
//   window.ZK.renderAvatar(targetEl, { size?: number, anon?: boolean })
//   window.ZK.avatarUrls()        -> array of all 120 curated paths
//   window.ZK.isCuratedAvatarUrl  -> shared validator (used by profile.js etc.)

(function () {
  "use strict";

  // Exact bound to the 120 on-disk assets (avatar_00..avatar_119) — mirrors
  // website/app.py::_CURATED_AVATAR_RE. Must stay in sync with that gate.
  const CURATED_RE = /^\/artifacts\/avatars\/avatar_(0\d|[1-9]\d|1[01]\d)\.svg$/;
  const AVATAR_COUNT = 120;
  // Shared with desktop header.js (CACHE_KEY_PREFIX) so a no-avatar user picks
  // the same random avatar on both surfaces until the server value is persisted.
  const CACHE_KEY_PREFIX = "zk-avatar-url-";
  const ALL_AVATARS = Array.from({ length: AVATAR_COUNT }, (_, i) =>
    `/artifacts/avatars/avatar_${String(i).padStart(2, "0")}.svg`
  );

  function isCuratedAvatarUrl(url) {
    return typeof url === "string" && CURATED_RE.test(url);
  }

  function avatarUrlFor(id) {
    const safe = Math.max(0, Math.min(AVATAR_COUNT - 1, parseInt(id, 10) || 0));
    return `/artifacts/avatars/avatar_${String(safe).padStart(2, "0")}.svg`;
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

  function cacheKey(profileId) { return CACHE_KEY_PREFIX + (profileId || "anon"); }

  function readCached(profileId) {
    try {
      const v = localStorage.getItem(cacheKey(profileId));
      return isCuratedAvatarUrl(v) ? v : null;
    } catch { return null; }
  }

  function writeCached(profileId, url) {
    try { localStorage.setItem(cacheKey(profileId), url); } catch (e) { void e; }
  }

  // Fire-and-forget persist of a freshly-assigned random avatar, so the same
  // avatar shows on desktop's next load. Non-blocking; failure is harmless
  // (the cache still pins it locally and the next assignment retries).
  async function persistAvatar(avatarId) {
    try {
      const token = await authToken();
      if (!token) return;
      await fetch("/api/me/avatar", {
        method: "PUT",
        credentials: "include",
        headers: { "Authorization": "Bearer " + token, "Content-Type": "application/json" },
        body: JSON.stringify({ avatar_id: avatarId }),
      });
    } catch (e) { void e; }
  }

  // Mirror of desktop header.js resolveAvatarUrl: server > cache > random-assign.
  async function resolveAvatarUrl(opts) {
    // Anon: fresh random curated avatar per load (no cache, no persist), matching
    // desktop spec §8. Header anon state normally renders the person glyph, but
    // callers may still request an anon avatar image explicitly.
    if (opts.anon) return avatarUrlFor(Math.floor(Math.random() * AVATAR_COUNT));

    const me = await fetchMe();
    if (me && isCuratedAvatarUrl(me.avatar_url)) {
      // Warm the shared cache (parity with desktop header.js) so the next load
      // — and the other surface — skip the /api/me round-trip.
      if (me.id) writeCached(me.id, me.avatar_url);
      return me.avatar_url;
    }

    const profileId = me && me.id;
    if (profileId) {
      const cached = readCached(profileId);
      if (cached) return cached;
    }
    const randomId = Math.floor(Math.random() * AVATAR_COUNT);
    const url = avatarUrlFor(randomId);
    if (profileId) { writeCached(profileId, url); persistAvatar(randomId); }
    return url;
  }

  /**
   * Render the current user's avatar into `target`.
   *   opts.size  — pixel dimension (default 38)
   *   opts.anon  — skip /api/me and render a random curated avatar
   */
  async function renderAvatar(target, opts = {}) {
    if (!target) return;
    const size = Number(opts.size) > 0 ? Number(opts.size) : 38;
    const url = await resolveAvatarUrl(opts);
    target.classList.remove("initials");
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
