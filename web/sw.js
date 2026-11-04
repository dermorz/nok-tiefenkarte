/* Service Worker: App-Hülle vorab, Kacheln/Uferlinien aus den Abschnitts-Caches (sec-*), index.json network-first. */
const SHELL = "shell-__VERSION__";
const FILES = ["./", "index.html", "index.json", "rules.json", "app.js", "style.css", "manifest.webmanifest", "icon.svg", "apple-touch-icon.png", "icon-512.png",
  "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k.startsWith("shell-") && k !== SHELL).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;   // basemap.de: nur online
  if (url.pathname.endsWith("/index.json") || url.pathname.endsWith("/rules.json")) {
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request)));
    return;
  }
  if (/\/(tiles|sections|ufer)\//.test(url.pathname)) {
    // exakte Version aus dem Cache, sonst Netz, offline notfalls ältere Version desselben Pfads
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).catch(() =>
      caches.match(e.request, { ignoreSearch: true }).then((old) => old || new Response("", { status: 504 })))));
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request)));
});
