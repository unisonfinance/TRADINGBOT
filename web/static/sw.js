const CACHE_NAME = 'trekbot-v1';
const PRECACHE_URLS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/firebase-config.js',
  '/static/firestore.js',
  '/static/logo.svg',
  '/static/favicon.ico',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Never cache API calls or POST requests
  if (url.pathname.startsWith('/api/') || event.request.method !== 'GET') {
    return;
  }

  // Network-first for HTML pages, cache-first for static assets
  if (event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  } else {
    event.respondWith(
      caches.match(event.request).then(cached => cached || fetch(event.request))
    );
  }
});
