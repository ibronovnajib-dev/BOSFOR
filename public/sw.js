/* Босфор — Service Worker: сайт работает быстрее и открывается офлайн */
const CACHE = 'bosfor-v2';
const CORE = [
  './', './index.html', './privacy.html', './manifest.webmanifest',
  './icons/icon-192.png', './icons/icon-512.png',
  './img/hero.jpg', './img/logo.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  // HTML — всегда свежий; картинки и иконки — из кэша
  if (url.origin === location.origin && /\.(jpg|jpeg|png|webmanifest|svg)$/.test(url.pathname)) {
    e.respondWith(
      caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return res;
      }))
    );
    return;
  }
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
