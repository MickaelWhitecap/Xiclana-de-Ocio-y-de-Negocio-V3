/* Service worker de la app de Xiclana.
   Solo guarda la portada y sus imágenes para poder abrir la app sin conexión.
   NO toca las peticiones a Supabase ni a otros dominios: el catálogo se sigue
   pidiendo igual que en la web (y ya se guarda en el propio navegador),
   así la app no gasta ni un byte más del cupo gratuito de Supabase. */
const CACHE = "xiclana-app-v1";
const BASICOS = ["./", "index.html", "supabase-config.js", "cabecera.webp", "logo-on.webp", "icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(BASICOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // Supabase, fuentes, mapas: sin tocar
  if (url.pathname.endsWith("/admin.html")) return; // la administración, siempre directa
  // Primero la red (así siempre se ve la versión nueva); si no hay conexión, la copia guardada.
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && BASICOS.some((b) => url.pathname.endsWith("/" + b.replace("./", "")))) {
          const copia = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copia));
        }
        return res;
      })
      .catch(() =>
        caches.match(req, { ignoreSearch: true }).then((r) => r || (req.mode === "navigate" ? caches.match("index.html") : Response.error()))
      )
  );
});
