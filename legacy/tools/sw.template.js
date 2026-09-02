/* Offline-first com atualização: responde do cache e revalida por trás
 * (stale-while-revalidate). O nome do cache é versionado pelo build
 * (tools/build.sh troca __V__), o que também força reinstalação do SW. */
const CACHE = "bienal-__V__";
const ASSETS = ["./", "index.html", "map.json", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.open(CACHE).then(async cache => {
      const hit = await cache.match(e.request, { ignoreSearch: true });
      const refresh = fetch(e.request)
        .then(res => {
          if (res.ok) cache.put(e.request, res.clone());
          return res;
        })
        .catch(() => hit);          // offline: fica no cache
      if (hit) { e.waitUntil(refresh); return hit; }
      return refresh;
    })
  );
});
