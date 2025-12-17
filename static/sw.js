// Простейший Service Worker
self.addEventListener('install', (event) => {
    console.log('Service Worker установлен');
    self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
    // Здесь можно настроить кэширование, но пока просто пропускаем запросы
    event.respondWith(fetch(event.request));
});