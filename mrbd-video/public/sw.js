// 앱 셸 프리캐시 → 안경에서 앱이 네트워크 없이도 즉시 뜸.
// 영상(/media)과 API는 캐시하지 않음 (영상은 앱이 IndexedDB에 직접 저장).
const CACHE = 'mrbd-video-v12';  // v2: 실험 연동 (freeze/resume), v3: 영상 조각 저장, v4: 이어받기, v5: TOR 경고 (alert), v6: 시선 보정 점 (calib), v7: 점을 단색으로 (안경에서 그라디언트가 안 보임), v8: HTTP 캐시를 건너뛰고 받음, v9: 보정 점 시험 버튼, 버전 보고, v10: 임의 위치 점 (검증), v11: 보정 코드를 calib.js로, v12: blank (보정 중 메뉴 가림)
// Cloudflare turns the server's no-cache into max-age=14400 (Browser Cache TTL), so the browser's HTTP
// cache would keep old app files for 4 h: install with cache 'reload', refresh with cache 'no-cache'.
const SHELL = ['/', '/index.html', '/app.js', '/calib.js', '/style.css', '/manifest.json', '/icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting()));
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
      const net = fetch(url.href, { cache: 'no-cache' })  // not e.request: a navigate request takes no init
        .then((r) => { if (r.ok) c.put(e.request, r.clone()); return r; })
        .catch(() => hit);
      return hit || net;
    })
  );
});
