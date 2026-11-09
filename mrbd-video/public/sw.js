// 앱 셸 프리캐시 → 안경에서 앱이 네트워크 없이도 즉시 뜸.
// 영상(/media)과 API는 캐시하지 않음 (영상은 앱이 IndexedDB에 직접 저장).
const CACHE = 'mrbd-video-v3';  // v2: 실험 연동 (freeze/resume), v3: 영상 조각 저장
const SHELL = ['/', '/index.html', '/app.js', '/style.css', '/manifest.json', '/icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) return;
  // stale-while-revalidate: 캐시로 즉시 응답, 뒤에서 최신본 갱신
  e.respondWith(
    caches.open(CACHE).then(async (c) => {
      const hit = await c.match(e.request, { ignoreSearch: true });
      const net = fetch(e.request)
        .then((r) => { if (r.ok) c.put(e.request, r.clone()); return r; })
        .catch(() => hit);
      return hit || net;
    })
  );
});
