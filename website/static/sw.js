// Service Worker — Zettelkasten mobile shell cache (iter mobile-1a Phase 6)
// Placeholder icons: teal-on-dark 'Z'. Replace icons before shipping to stores.

const CACHE = 'zk-shell-v5';  // v5: precache the rest of the critical mobile JS (install/avatar/summarizer/sheet) + manifest so the shell hydrates on bad networks; activate purges v4 and any stale assets behind "UI doesn't show up properly" reports. v4: drop ignoreSearch on /m/js/ + /m/css/ + /static/ so cache-busters actually invalidate (Vedant OAuth incident 2026-05-26)

const SHELL_URLS = [
  '/m/',
  '/m/knowledge-graph',
  '/m/css/mobile.css',
  '/m/js/shell.js',
  '/m/js/auth-modal.js',
  // Core mobile JS — precached so the shell + install affordance hydrate even
  // on a flaky first paint (rural 2G/3G) and offline.
  '/m/js/install-prompt.js',
  '/m/js/avatar.js',
  '/m/js/summarizer.js',
  '/m/js/hamburger-sheet.js',
  // Shared static (loaded by mobile via /js/ mount) — added for offline shell completeness (A-2).
  '/js/add_zettel_api.js',
  '/js/zk_skeleton_typewriter.js',
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon-180.png',
  '/favicon.svg',
];

// Install: precache shell URLs. Do NOT skipWaiting — let user control activation.
self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // addAll fails atomically; missing asset = install failure (intentional).
      return cache.addAll(SHELL_URLS);
    })
  );
});

// Activate: delete old cache versions so stale shells don't persist.
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (key) { return key !== CACHE; })
            .map(function (key) { return caches.delete(key); })
      );
    })
  );
});

// Fetch: strategy depends on path.
self.addEventListener('fetch', function (event) {
  // Only intercept GET.
  if (event.request.method !== 'GET') return;

  var url = new URL(event.request.url);

  // Bypass: API, KG data, auth endpoints — always network, never cache.
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/kg/content/') ||
    url.pathname.startsWith('/auth/')
  ) {
    return; // let browser handle normally
  }

  // HTML in /m/* — network-first, fall back to cache.
  // Normalize URL (strip query string) so versioned paths share one cache entry.
  if (url.pathname.startsWith('/m/') && url.pathname.indexOf('.') === -1) {
    var canonicalHtml = new Request(url.origin + url.pathname);
    event.respondWith(
      fetch(event.request)
        .then(function (resp) {
          var clone = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(canonicalHtml, clone); });
          return resp;
        })
        .catch(function () {
          return caches.match(canonicalHtml, { ignoreSearch: true });
        })
    );
    return;
  }

  // Static assets: /static/*, /m/css/*, /m/js/*, /favicon.svg — cache-first, network fallback + update.
  // Key cache entries on the FULL URL (including ?v=... cache-buster) so a
  // version bump in HTML produces a cache miss → network fetch → new entry.
  // The previous "normalize to canonical + ignoreSearch:true" pattern looked
  // efficient but silently stripped the version key, so old JS persisted
  // across deploys until the SW activate event purged the entire cache. See
  // research synthesis 2026-05-26 (Vedant OAuth incident) for evidence.
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname.startsWith('/m/css/') ||
    url.pathname.startsWith('/m/js/') ||
    url.pathname === '/favicon.svg'
  ) {
    event.respondWith(
      caches.match(event.request).then(function (cached) {
        var networkFetch = fetch(event.request).then(function (resp) {
          var clone = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(event.request, clone); });
          return resp;
        });
        return cached || networkFetch;
      })
    );
    return;
  }

  // Everything else: passthrough (no caching).
});
