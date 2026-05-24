// Service Worker — Zettelkasten mobile shell cache (iter mobile-1a Phase 6)
// Placeholder icons: teal-on-dark 'Z'. Replace icons before shipping to stores.

const CACHE = 'zk-shell-v1';

const SHELL_URLS = [
  '/m/',
  '/m/knowledge-graph',
  '/m/css/mobile.css',
  '/m/js/shell.js',
  '/m/js/capture.js',
  '/m/js/auth-modal.js',
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
  if (url.pathname.startsWith('/m/') && url.pathname.indexOf('.') === -1) {
    event.respondWith(
      fetch(event.request)
        .then(function (resp) {
          var clone = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(event.request, clone); });
          return resp;
        })
        .catch(function () {
          return caches.match(event.request);
        })
    );
    return;
  }

  // Static assets: /static/*, /m/css/*, /m/js/*, /favicon.svg — cache-first, network fallback + update.
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
