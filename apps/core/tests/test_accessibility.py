"""Accesibilidad mínima WCAG 2.1 AA en lo que usa el huésped (RNF-UX-06).

Revisión automática de las reglas que se pueden comprobar en el HTML:
- 3.1.1 idioma de la página (`<html lang>`);
- 1.1.1 texto alternativo en imágenes;
- 1.3.1 / 4.1.2 cada campo tiene etiqueta (label, aria-label o aria-labelledby);
- 4.1.2 cada botón y enlace tiene nombre accesible;
- 2.4.2 título de página y 2.4.1 enlace para saltar al contenido;
- 1.3.1 un solo encabezado principal (`<h1>`).
El contraste de colores se revisó con la paleta del diseño (tokens de `tailwind.config.js`).
"""

from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.urls import reverse

from conftest import BUSINESS_DATE

SKIP_INPUTS = {"hidden", "submit", "button", "reset", "image"}


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.problems, self.labels_for, self.fields = [], set(), []
        self.lang = self.title = None
        self.h1 = 0
        self.label_depth = 0
        self.open = []  # (tag, attrs, text)
        self.skip_link = False
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self.h1 += 1
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.labels_for.add(a["for"])
        if tag == "img" and "alt" not in a:
            self.problems.append(f"img sin alt: {a.get('src')}")
        if tag in ("input", "select", "textarea") and a.get("type", "text") not in SKIP_INPUTS:
            named = self.label_depth > 0 or a.get("aria-label") or a.get("aria-labelledby")
            self.fields.append((a.get("name"), a.get("id"), bool(named)))
        if tag in ("button", "a"):
            self.open.append([tag, a, ""])
            if tag == "a" and a.get("href", "").startswith("#") and "sr-only" in a.get("class", ""):
                self.skip_link = True

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("button", "a") and self.open:
            t, a, text = self.open.pop()
            if not (text.strip() or a.get("aria-label") or a.get("title")):
                self.problems.append(f"{t} sin nombre accesible: {a}")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        for item in self.open:
            item[2] += data

    def report(self):
        problems = list(self.problems)
        if not self.lang:
            problems.append("html sin lang")
        if not (self.title or "").strip():
            problems.append("sin <title>")
        if self.h1 != 1:
            problems.append(f"{self.h1} encabezados h1")
        if not self.skip_link:
            problems.append("sin enlace para saltar al contenido")
        for name, id_, named in self.fields:
            if not named and id_ not in self.labels_for:
                problems.append(f"campo sin etiqueta: {name}")
        return problems


def audit(html: str) -> list[str]:
    parser = Audit()
    parser.feed(html)
    return parser.report()


@pytest.fixture
def guest_pages(setup, book):
    r = book()
    arrival = BUSINESS_DATE + timedelta(days=2)
    q = f"llegada={arrival.isoformat()}&salida={(arrival + timedelta(days=2)).isoformat()}&adultos=2"
    return [
        reverse("portal:home", args=[r.portal_token]),
        reverse("portal:precheckin", args=[r.portal_token]),
        reverse("portal:survey", args=[r.portal_token]),
        reverse("portal:complaint_book", args=[setup.hotel.code]),
        reverse("booking_engine:search"),
        reverse("booking_engine:search") + "?" + q,
        reverse("booking_engine:book") + f"?{q}&tipo={setup.double.pk}&plan={setup.rack.pk}",
        reverse("booking_engine:group"),
        reverse("booking_engine:confirmation", args=[r.portal_token]),
    ]


def test_guest_facing_pages_meet_basic_wcag_rnf_ux_06(client, guest_pages):
    failures = {}
    for url in guest_pages:
        resp = client.get(url)
        assert resp.status_code == 200, url
        problems = audit(resp.content.decode())
        if problems:
            failures[url] = problems
    assert not failures, failures


def test_auditor_detects_problems():
    bad = '<html><title>x</title><img src="a.png"><input name="email"><button></button><h1>a</h1><h1>b</h1></html>'
    problems = " | ".join(audit(bad))
    for expected in (
        "html sin lang",
        "img sin alt",
        "campo sin etiqueta: email",
        "button sin nombre",
        "2 encabezados h1",
        "saltar al contenido",
    ):
        assert expected in problems
    good = (
        '<html lang="es"><title>x</title><a href="#c" class="sr-only">Saltar</a><h1>T</h1>'
        '<label for="e">Correo</label><input id="e" name="email"><img src="a" alt=""><button>OK</button></html>'
    )
    assert audit(good) == []
