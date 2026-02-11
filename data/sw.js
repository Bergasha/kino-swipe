self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

// Android Chrome REQUIRES a fetch handler to be considered a PWA
self.addEventListener('fetch', (event) => {
    event.respondWith(fetch(event.request));
});
