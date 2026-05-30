// profile.js — mobile profile page: auth + unauth states + avatar picker (T11).
//
// Canonical endpoints (NOT /api/profile — that was redundant with /api/me):
//   GET   /api/me           → { id, email, name, avatar_url, profile_source }
//   PUT   /api/me/avatar    → body { avatar_id: 0..119 } → writes core.profiles.avatar_url
//
// Session is read from window.ZKAuth (auth-core.js stores in localStorage,
// not cookies); auth-state-change events trigger re-render.

(function () {
  "use strict";

  function escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function isCuratedAvatarUrl(url) {
    if (window.ZK && typeof window.ZK.isCuratedAvatarUrl === "function") {
      return window.ZK.isCuratedAvatarUrl(url);
    }
    return typeof url === "string"
      && /^\/artifacts\/avatars\/avatar_(0[0-9]|[1-5][0-9])\.svg$/.test(url);
  }
  function safeAvatarUrl(url) {
    return isCuratedAvatarUrl(url) ? url : "/artifacts/avatars/avatar_00.svg";
  }
  function avatarIdFromUrl(url) {
    var m = /\/avatar_(\d{2})\.svg$/.exec(String(url || ""));
    return m ? Number(m[1]) : null;
  }

  async function authToken() {
    try {
      if (typeof window.getAuthToken === "function") {
        var t = window.getAuthToken();
        if (t) return t;
      }
      if (window.ZKAuth && typeof window.ZKAuth.getSession === "function") {
        var s = await window.ZKAuth.getSession();
        if (s && s.access_token) return s.access_token;
      }
    } catch (e) { void e; }
    return "";
  }

  async function hasSession() {
    var t = await authToken();
    return Boolean(t);
  }

  async function loadMe() {
    var token = await authToken();
    if (!token) return null;
    try {
      var r = await fetch("/api/me", {
        credentials: "include",
        headers: { "Authorization": "Bearer " + token },
      });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  async function putAvatar(avatarId) {
    var token = await authToken();
    if (!token) throw new Error("not signed in");
    var r = await fetch("/api/me/avatar", {
      method: "PUT",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token,
      },
      body: JSON.stringify({ avatar_id: avatarId }),
    });
    if (!r.ok) {
      var msg = "save failed: " + r.status;
      try { var b = await r.json(); if (b && b.detail) msg = String(b.detail); } catch (e) { void e; }
      throw new Error(msg);
    }
    return await r.json();
  }

  function renderUnauth() {
    document.getElementById("profile-unauth").hidden = false;
    document.getElementById("profile-auth").hidden = true;
    var btn = document.getElementById("profile-signin-btn");
    btn.addEventListener("click", function () {
      // Reuse the existing OAuth modal — programmatically click the avatar pill.
      var avatarBtn = document.getElementById("m-avatar-btn");
      if (avatarBtn) avatarBtn.click();
    });
  }

  function renderAuth(me) {
    document.getElementById("profile-unauth").hidden = true;
    document.getElementById("profile-auth").hidden = false;
    document.getElementById("profile-email").textContent = me.email || "";

    var avatarSlot = document.getElementById("profile-avatar");
    var currentUrl = safeAvatarUrl(me.avatar_url);
    avatarSlot.dataset.currentUrl = currentUrl;
    avatarSlot.innerHTML =
      '<img src="' + escHtml(currentUrl) + '" width="72" height="72" alt="" class="zk-avatar-img">';

    renderPicker(currentUrl);
    document.getElementById("profile-signout").addEventListener("click", signOut);
  }

  function renderPicker(currentUrl) {
    var picker = document.getElementById("avatar-picker");
    var urls = (window.ZK && window.ZK.avatarUrls) ? window.ZK.avatarUrls() : [];
    if (!urls.length) return;

    var io = ("IntersectionObserver" in window) ? new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var img = e.target.querySelector("img");
          if (img && img.dataset.src && !img.src) img.src = img.dataset.src;
          io.unobserve(e.target);
        }
      });
    }, { rootMargin: "80px" }) : null;

    urls.forEach(function (url) {
      var cell = document.createElement("button");
      cell.type = "button";
      cell.className = "m-avatar-cell" + (url === currentUrl ? " is-selected" : "");
      cell.dataset.url = url;
      cell.setAttribute("aria-label", "Pick avatar " + url.replace(/^.*avatar_/, "").replace(/\.svg$/, ""));
      cell.innerHTML = '<img data-src="' + escHtml(url) + '" width="56" height="56" alt="">';
      cell.addEventListener("click", function () { selectAvatar(url, cell); });
      picker.appendChild(cell);
      if (io) io.observe(cell); else {
        var img = cell.querySelector("img");
        if (img) img.src = img.dataset.src;
      }
    });
  }

  async function selectAvatar(url, cellEl) {
    if (!isCuratedAvatarUrl(url)) return;
    var id = avatarIdFromUrl(url);
    if (id === null) return;

    var avatarSlot = document.getElementById("profile-avatar");
    var prevUrl = avatarSlot.dataset.currentUrl || "/artifacts/avatars/avatar_00.svg";
    var prev = document.querySelector(".m-avatar-cell.is-selected");

    // Optimistic UI
    if (prev) prev.classList.remove("is-selected");
    cellEl.classList.add("is-selected");
    avatarSlot.innerHTML =
      '<img src="' + escHtml(url) + '" width="72" height="72" alt="" class="zk-avatar-img">';

    try {
      var resp = await putAvatar(id);
      var resolved = (resp && isCuratedAvatarUrl(resp.avatar_url)) ? resp.avatar_url : url;
      avatarSlot.dataset.currentUrl = resolved;
      document.dispatchEvent(new CustomEvent("zk:avatar-changed", { detail: { url: resolved } }));
    } catch (err) {
      // Revert BOTH the picker cell AND the large avatar preview (Codex P2).
      console.error(err);
      cellEl.classList.remove("is-selected");
      if (prev) prev.classList.add("is-selected");
      avatarSlot.innerHTML =
        '<img src="' + escHtml(prevUrl) + '" width="72" height="72" alt="" class="zk-avatar-img">';
      window.alert("Could not save avatar.");
    }
  }

  async function signOut() {
    try {
      if (window.ZKAuth && typeof window.ZKAuth.signOut === "function") {
        await window.ZKAuth.signOut();
      } else if (typeof window.signOut === "function") {
        await window.signOut();
      }
    } catch (err) {
      console.error("sign-out failed:", err);
    }
    location.assign("/m/profile");
  }

  async function init() {
    if (!(await hasSession())) { renderUnauth(); return; }
    var me = await loadMe();
    if (!me) { renderUnauth(); return; }
    renderAuth(me);
  }

  function bootWhenAuthReady() {
    if (window.ZKAuth && window.ZKAuth.ready && typeof window.ZKAuth.ready.then === "function") {
      window.ZKAuth.ready.then(init);
    } else {
      init();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootWhenAuthReady);
  } else {
    bootWhenAuthReady();
  }
})();
