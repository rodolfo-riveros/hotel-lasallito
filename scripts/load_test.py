"""Prueba de carga del PMS contra un servidor en marcha (RNF-REN-01 y RNF-REN-02).

Simula N usuarios concurrentes que recorren las pantallas de recepción y buscan reservas.
Mide p50/p95 por pantalla y compara con los objetivos:
  - pantallas de recepción < 2 s
  - búsqueda de reservas < 1 s

Uso (las credenciales van en variables de entorno, nunca en el código):
    set LOAD_TEST_USER=recepcion
    set LOAD_TEST_PASSWORD=...
    python scripts/load_test.py --base http://127.0.0.1:8000 --users 50 --rounds 5

Use un servidor con varios procesos (gunicorn -w 4 en Linux o waitress en Windows); `runserver
--nothreading` atiende de a una petición y no representa producción.
"""

import argparse
import http.cookiejar
import os
import random
import re
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request

PAGES = [
    ("Tablero", "/", 2.0),
    ("Recepción", "/recepcion/", 2.0),
    ("Reservas", "/reservas/", 2.0),
    ("Rack de habitaciones", "/habitaciones/", 2.0),
    ("Búsqueda de reserva", "/reservas/?q=Quispe", 1.0),
    ("Housekeeping", "/housekeeping/", 2.0),
]


def login(base, username, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    html = opener.open(f"{base}/cuenta/ingresar/", timeout=30).read().decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
    data = urllib.parse.urlencode({"csrfmiddlewaretoken": token, "username": username, "password": password})
    req = urllib.request.Request(
        f"{base}/cuenta/ingresar/", data=data.encode(), headers={"Referer": f"{base}/cuenta/ingresar/"}
    )
    resp = opener.open(req, timeout=30)
    if "/cuenta/ingresar/" in resp.geturl():
        raise SystemExit("No se pudo ingresar: revise LOAD_TEST_USER y LOAD_TEST_PASSWORD.")
    return opener


def worker(base, opener, rounds, results, errors, lock, think=0.0):
    rnd = random.Random()  # noqa: S311 - solo reparte pausas
    for _ in range(rounds):
        for name, path, _limit in PAGES:
            if think:
                time.sleep(rnd.uniform(think / 2, think * 1.5))  # el usuario lee la pantalla
            t0 = time.perf_counter()
            try:
                opener.open(base + path, timeout=60).read()
                elapsed = time.perf_counter() - t0
                with lock:
                    results.setdefault(name, []).append(elapsed)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(f"{name}: {exc}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--think",
        type=float,
        default=0.0,
        help="Segundos promedio que cada usuario mira la pantalla antes de pasar a otra",
    )
    args = parser.parse_args()
    user, password = os.environ.get("LOAD_TEST_USER"), os.environ.get("LOAD_TEST_PASSWORD")
    if not user or not password:
        raise SystemExit("Defina LOAD_TEST_USER y LOAD_TEST_PASSWORD.")
    base = args.base.rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise SystemExit("--base debe empezar con http:// o https://")
    print(f"Ingresando {args.users} usuarios...")
    openers = [login(base, user, password) for _ in range(args.users)]
    results, errors, lock = {}, [], threading.Lock()
    threads = [
        threading.Thread(target=worker, args=(base, o, args.rounds, results, errors, lock, args.think))
        for o in openers
    ]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - t0
    ok = True
    print(f"\n{'Pantalla':<24}{'n':>6}{'p50 (s)':>10}{'p95 (s)':>10}{'meta':>8}  estado")
    for name, _path, limit in PAGES:
        times = sorted(results.get(name, []))
        if not times:
            continue
        p50 = statistics.median(times)
        p95 = times[max(0, int(len(times) * 0.95) - 1)]
        passed = p95 <= limit
        ok &= passed
        print(
            f"{name:<24}{len(times):>6}{p50:>10.2f}{p95:>10.2f}{limit:>8.1f}  {'OK' if passed else 'LENTO'}"
        )
    n = sum(len(v) for v in results.values())
    print(f"\n{n} peticiones en {total:.1f} s ({n / total:.1f}/s) · errores: {len(errors)}")
    for e in errors[:10]:
        print("  ", e)
    sys.exit(0 if ok and not errors else 1)


if __name__ == "__main__":
    main()
