"""Sitio web de reservas del hotel (RF-WEB-01 a 06).

Es público: no requiere usuario. Habla español, inglés y portugués, muestra precios
en soles o dólares y reutiliza tarifas, disponibilidad, reservas y la pasarela de pago.
"""

import json
from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_countries.fields import CountryField

from apps.accounts.decorators import require_perm
from apps.portal.views import LANGS
from apps.rates.models import RatePlan
from apps.reservations.models import Reservation
from apps.rooms.models import RoomType
from apps.tours.models import Service

from . import services
from .models import GroupRequest


def _lang(request):
    lang = (
        request.GET.get("lang")
        or request.session.get("portal_lang")
        or (translation.get_language_from_request(request) or "es").lower()
    )
    lang = (
        lang
        if lang in LANGS
        else ("pt-br" if lang.startswith("pt") else "en" if lang.startswith("en") else "es")
    )
    request.session["portal_lang"] = lang
    return lang


def _render(request, template, ctx, prop):
    lang = _lang(request)
    with translation.override(lang):
        ctx.update(
            {
                "p": prop,
                "lang": lang,
                "langs": [("es", "ES"), ("en", "EN"), ("pt-br", "PT")],
                "currencies": services.currencies(prop),
            }
        )
        return render(request, template, ctx)


def _property(request):
    prop = services.public_property(request.GET.get("hotel"))
    if prop is None:
        raise Http404
    return prop


def _dates(request, prop):
    today = prop.current_business_date()
    try:
        arrival = date.fromisoformat(request.GET.get("llegada", ""))
    except ValueError:
        arrival = today + timedelta(days=1)
    try:
        departure = date.fromisoformat(request.GET.get("salida", ""))
    except ValueError:
        departure = arrival + timedelta(days=2)
    return arrival, departure


def _int(value, default, low=0, high=10):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def search(request):
    """RF-WEB-01/02: búsqueda, habitaciones y precios. Incluye datos estructurados de Hotel (RF-WEB-06)."""
    prop = _property(request)
    arrival, departure = _dates(request, prop)
    adults, children = _int(request.GET.get("adultos"), 2, 1, 8), _int(request.GET.get("ninos"), 0, 0, 6)
    currency = request.GET.get("moneda", "PEN")
    currency = currency if currency in services.currencies(prop) else "PEN"
    promo = request.GET.get("promo", "").strip()[:30]
    offers, error = [], ""
    if "llegada" in request.GET:
        try:
            offers = services.search(
                prop, arrival, departure, adults, children, currency=currency, promo_code=promo
            )
        except ValidationError as exc:
            error = " ".join(exc.messages)
    params = {
        "llegada": arrival.isoformat(),
        "salida": departure.isoformat(),
        "adultos": adults,
        "ninos": children,
        "moneda": currency,
        "promo": promo,
    }
    return _render(
        request,
        "booking_engine/search.html",
        {
            "offers": offers,
            "error": error,
            "searched": "llegada" in request.GET,
            "params": params,
            "nights": (departure - arrival).days,
            "jsonld": json.dumps(_jsonld(request, prop), ensure_ascii=False),
            "room_types": (
                RoomType.objects.filter(property=prop, is_active=True).order_by("sort_order")
                if "llegada" not in request.GET
                else []
            ),
        },
        prop,
    )


def _jsonld(request, prop):
    return {
        "@context": "https://schema.org",
        "@type": "Hotel",
        "name": prop.name,
        "url": request.build_absolute_uri(reverse("booking_engine:search")),
        "telephone": prop.phone,
        "email": prop.email,
        "starRating": {"@type": "Rating", "ratingValue": prop.category_stars or 3},
        "checkinTime": (
            prop.check_in_time.strftime("%H:%M") if hasattr(prop.check_in_time, "strftime") else ""
        ),
        "checkoutTime": (
            prop.check_out_time.strftime("%H:%M") if hasattr(prop.check_out_time, "strftime") else ""
        ),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": prop.address,
            "addressLocality": prop.city,
            "addressRegion": prop.region,
            "addressCountry": "PE",
        },
    }


class BookingForm(forms.Form):
    first_name = forms.CharField(label=gettext_lazy("Nombres"), max_length=100)
    last_name = forms.CharField(label=gettext_lazy("Apellidos"), max_length=100)
    email = forms.EmailField(label=gettext_lazy("Correo"))
    phone = forms.CharField(label=gettext_lazy("Teléfono / WhatsApp"), max_length=30, required=False)
    country = CountryField(blank=True).formfield(label=gettext_lazy("País"), required=False)
    special_requests = forms.CharField(
        label=gettext_lazy("Pedidos especiales (hora de llegada, dieta, tren)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    payment = forms.ChoiceField(
        label=gettext_lazy("Pago"),
        widget=forms.RadioSelect,
        initial="online",
        choices=[
            ("online", gettext_lazy("Pagar ahora con tarjeta")),
            ("hotel", gettext_lazy("Pagar en el hotel")),
        ],
    )
    accept = forms.BooleanField(
        label=gettext_lazy(
            "Acepto la política de cancelación y el tratamiento de mis datos " "personales (Ley 29733)."
        )
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # trampa para bots


def book(request):
    """RF-WEB-03/04: datos del huésped, extras y pago en línea o en el hotel."""
    prop = _property(request)
    arrival, departure = _dates(request, prop)
    adults, children = _int(request.GET.get("adultos"), 2, 1, 8), _int(request.GET.get("ninos"), 0, 0, 6)
    currency = request.GET.get("moneda", "PEN")
    currency = currency if currency in services.currencies(prop) else "PEN"
    promo = request.GET.get("promo", "").strip()[:30]
    room_type = get_object_or_404(RoomType, pk=request.GET.get("tipo"), property=prop, is_active=True)
    plan = get_object_or_404(
        RatePlan, pk=request.GET.get("plan"), property=prop, is_active=True, is_public=True
    )
    from apps.rates.services import quote

    q = quote(plan, room_type, arrival, departure, adults, children, currency=currency, promo_code=promo)
    extras = list(
        Service.objects.filter(property=prop, is_active=True, is_public=True).order_by("kind", "name")
    )
    form = BookingForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and not form.cleaned_data["website"]:
        cd = form.cleaned_data
        chosen = []
        for s in extras:
            pax = _int(request.POST.get(f"extra_{s.pk}"), 0, 0, 10)
            if pax:
                day = (
                    arrival if s.kind == Service.Kind.AIRPORT else min(arrival + timedelta(days=1), departure)
                )
                chosen.append((s, pax, day))
        data = services.WebBooking(
            first_name=cd["first_name"],
            last_name=cd["last_name"],
            email=cd["email"],
            phone=cd["phone"],
            country=cd["country"] or "",
            language=_lang(request),
            special_requests=cd["special_requests"],
            pay_online=cd["payment"] == "online",
            extras=chosen,
        )
        try:
            r = services.book(
                prop,
                plan,
                room_type,
                arrival,
                departure,
                adults,
                children,
                data,
                currency=currency,
                promo_code=promo,
            )
        except ValidationError as exc:
            for m in exc.messages:
                messages.error(request, m)
        else:
            done = reverse("booking_engine:confirmation", args=[r.portal_token])
            if data.pay_online:
                from apps.payments.gateways import get_gateway
                from apps.payments.services import create_payment

                payment = create_payment(
                    prop,
                    services.amount_due(r),
                    f"{prop.name} · {r.code}",
                    reservation=r,
                    email=cd["email"],
                    currency=r.currency,
                    is_deposit=True,
                    return_url=request.build_absolute_uri(done),
                )
                return redirect(get_gateway().checkout_url(payment))
            return redirect(done)
    return _render(
        request,
        "booking_engine/book.html",
        {
            "form": form,
            "q": q,
            "room_type": room_type,
            "plan": plan,
            "arrival": arrival,
            "departure": departure,
            "adults": adults,
            "children": children,
            "extras": extras,
            "currency": currency,
            "back": reverse("booking_engine:search") + "?" + request.GET.urlencode(),
        },
        prop,
    )


def confirmation(request, token):
    r = get_object_or_404(
        Reservation.objects.select_related("guest", "room_type", "rate_plan", "property"), portal_token=token
    )
    return _render(
        request,
        "booking_engine/confirmation.html",
        {
            "r": r,
            "paid": r.status == Reservation.Status.GUARANTEED,
            "extras": r.service_bookings.select_related("service"),
            "portal": reverse("portal:home", args=[r.portal_token]),
        },
        r.property,
    )


class GroupForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = GroupRequest
        fields = ["name", "company", "email", "phone", "arrival", "departure", "rooms", "pax", "notes"]
        widgets = {
            "arrival": forms.DateInput(attrs={"type": "date"}),
            "departure": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cd = super().clean()
        if cd.get("arrival") and cd.get("departure") and cd["departure"] <= cd["arrival"]:
            raise ValidationError(_("La salida debe ser posterior a la llegada."))
        return cd


def group_request(request):
    """RF-WEB-05: solicitud de cotización para grupos; avisa al equipo de ventas."""
    prop = _property(request)
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not form.cleaned_data["website"]:
            gr = form.save(commit=False)
            gr.property, gr.language = prop, _lang(request)
            gr.save()
            from apps.comms.services import notify_role

            for role in ("sales", "manager"):
                notify_role(
                    prop,
                    role,
                    _("Nueva solicitud de grupo"),
                    str(gr),
                    url=reverse("booking_engine:group_list"),
                )
        messages.success(request, _("Gracias. Le enviaremos la cotización a su correo."))
        return redirect(reverse("booking_engine:search"))
    return _render(request, "booking_engine/group.html", {"form": form}, prop)


def robots(request):
    sitemap = request.build_absolute_uri(reverse("booking_engine:sitemap"))
    body = (
        "User-agent: *\nAllow: /reservar/\nDisallow: /portal/\nDisallow: /pagos/\nDisallow: /cuenta/\n"
        f"Sitemap: {sitemap}\n"
    )
    return HttpResponse(body, content_type="text/plain")


def sitemap(request):
    urls = [request.build_absolute_uri(reverse(n)) for n in ("booking_engine:search", "booking_engine:group")]
    urls += [f"{urls[0]}?lang={code}" for code in ("en", "pt-br")]
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    )
    body += "".join(f"<url><loc>{u.replace('&', '&amp;')}</loc></url>" for u in urls) + "</urlset>"
    return HttpResponse(body, content_type="application/xml")


@require_perm("booking_engine.view")
def group_list(request):
    """Bandeja interna de solicitudes de grupo y ventas de la web."""
    prop = request.property
    if request.method == "POST" and request.user.has_pms_perm(prop, "booking_engine.edit"):
        GroupRequest.objects.filter(pk=request.POST.get("pk"), property=prop).update(
            status=request.POST.get("status", "new")
        )
        return redirect("booking_engine:group_list")
    since = prop.current_business_date() - timedelta(days=30)
    web = Reservation.objects.filter(property=prop, channel="web", created_at__date__gte=since)
    return render(
        request,
        "booking_engine/group_list.html",
        {
            "items": GroupRequest.objects.filter(property=prop)[:100],
            "statuses": GroupRequest.Status.choices,
            "web_count": web.count(),
            "web_recent": web.select_related("guest", "room_type").order_by("-created_at")[:10],
            "public_url": request.build_absolute_uri(reverse("booking_engine:search")),
        },
    )
