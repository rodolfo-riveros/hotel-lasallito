"""Aplicación web instalable (PWA) y contingencia sin internet (RNF-DIS-03, sección 1: "web responsive/PWA").

- `/manifest.webmanifest`: nombre, colores e íconos para instalar el PMS en el celular o la PC.
- `/sw.js`: service worker en la raíz para controlar todo el sitio. Guarda los archivos estáticos y la
  última versión de las pantallas de contingencia (llegadas, en casa, habitaciones) para consultarlas
  si se cae internet. Nunca guarda formularios ni respuestas POST.
- `/sin-conexion/`: página que se muestra cuando no hay red y la pantalla pedida no está guardada.
"""

import json

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control

# Pantallas que se guardan al visitarlas para tenerlas sin conexión.
CONTINGENCY_KEYS = ("arrivals", "in_house", "rooms")
CACHE_VERSION = "pms-v1"


@cache_control(max_age=3600)
def manifest(request):
    data = {
        "name": "PMS Hotel La Sallito",
        "short_name": "La Sallito",
        "description": "Sistema de gestión hotelera · Urubamba, Valle Sagrado",
        "lang": "es",
        "start_url": "/?origen=app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#faf8f5",
        "theme_color": "#561a24",
        "icons": [
            {"src": static("img/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("img/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("img/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "shortcuts": [
            {"name": "Recepción", "url": "/recepcion/"},
            {"name": "Reservas", "url": "/reservas/"},
            {"name": "Contingencia", "url": "/contingencia/"},
        ],
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False), content_type="application/manifest+json")


def _sw_source() -> str:
    precache = [
        reverse("pwa_offline"),
        static("css/app.css"),
        static("js/app.js"),
        static("vendor/htmx.min.js"),
        static("vendor/alpine.min.js"),
        static("img/icon-192.png"),
    ]
    contingency = [reverse("core:offline")] + [reverse("reports:report", args=[k]) for k in CONTINGENCY_KEYS]
    return f"""// Service worker del PMS (generado por apps/core/pwa.py)
const CACHE = "{CACHE_VERSION}";
const PRECACHE = {json.dumps(precache)};
const CONTINGENCY = {json.dumps(contingency)};
const OFFLINE = "{reverse("pwa_offline")}";

self.addEventListener("install", (e) => {{
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
}});

self.addEventListener("activate", (e) => {{
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
}});

self.addEventListener("fetch", (e) => {{
  const req = e.request;
  if (req.method !== "GET") return;  // formularios y pagos siempre van a la red
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith("{settings.STATIC_URL}")) {{
    // estáticos: caché primero y se refresca por detrás
    e.respondWith(
      caches.open(CACHE).then(async (c) => {{
        const hit = await c.match(req);
        const net = fetch(req).then((res) => {{ if (res.ok) c.put(req, res.clone()); return res; }}).catch(() => hit);
        return hit || net;
      }})
    );
    return;
  }}

  if (req.mode === "navigate") {{
    // páginas: red primero; las de contingencia se guardan para verlas sin internet
    const keep = CONTINGENCY.some((p) => url.pathname === p);
    e.respondWith(
      fetch(req)
        .then((res) => {{
          if (keep && res.ok && !res.redirected) caches.open(CACHE).then((c) => c.put(req, res.clone()));
          return res;
        }})
        .catch(async () => (await caches.match(req)) || (await caches.match(OFFLINE)))
    );
  }}
}});
"""


@cache_control(no_cache=True)
def service_worker(request):
    response = HttpResponse(_sw_source(), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline_shell(request):
    return render(request, "core/pwa_offline.html", {"pages": CONTINGENCY_KEYS})
