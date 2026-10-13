from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.crud import Crud
from apps.core.fields import blind_index
from apps.core.models import AuditLog

from .forms import CompanyForm, GuestForm
from .models import Company, Guest, LoyaltyTier
from .services import anonymize, find_duplicates, merge_guests

AUDIT_FIELDS = [
    "first_name",
    "last_name",
    "doc_type",
    "email",
    "phone",
    "nationality",
    "is_blacklisted",
    "tags",
]

company_crud = Crud(
    model=Company,
    module="guests",
    form_class=CompanyForm,
    columns=[
        (gettext_lazy("Razón social"), "legal_name"),
        (gettext_lazy("Tipo"), "kind"),
        (gettext_lazy("RUC"), "ruc"),
        (gettext_lazy("Crédito S/"), "credit_limit"),
        (gettext_lazy("Días"), "credit_days"),
        (gettext_lazy("Comisión %"), "commission_percent"),
        (gettext_lazy("Activa"), "is_active"),
    ],
    search=["legal_name", "trade_name", "ruc"],
    filters=["kind"],
)


def search_guests(q: str):
    qs = Guest.objects.all()
    if not q:
        return qs
    return qs.filter(
        Q(first_name__icontains=q)
        | Q(last_name__icontains=q)
        | Q(email__icontains=q)
        | Q(phone__icontains=q)
        | Q(doc_hash=blind_index(q))
    )


@require_perm("guests.view")
def guest_list(request):
    q = request.GET.get("q", "").strip()
    qs = search_guests(q)
    tag = request.GET.get("tag")
    if tag == "blacklist":
        qs = qs.filter(is_blacklisted=True)
    elif tag:
        qs = qs.filter(tags__icontains=tag)
    page = Paginator(qs.select_related("company"), 30).get_page(request.GET.get("page"))
    template = "guests/partials/guest_rows.html" if request.htmx else "guests/guest_list.html"
    return render(request, template, {"page": page, "q": q, "tag": tag, "tags": Guest.Tag.choices})


@require_perm("guests.view")
def guest_search_json(request):
    """Autocompletado para reservas y POS."""
    q = request.GET.get("q", "").strip()
    results = [
        {
            "id": g.pk,
            "text": f"{g.full_name} · {g.get_doc_type_display()} {g.masked_doc}",
            "blacklisted": g.is_blacklisted,
        }
        for g in search_guests(q)[:10]
    ]
    return JsonResponse({"results": results})


@require_perm("guests.view")
def guest_detail(request, pk):
    guest = get_object_or_404(Guest, pk=pk)
    show_sensitive = request.GET.get("ver") == "1"
    if show_sensitive:
        # RNF-SEG-03: acceso a datos personales queda auditado
        audit.log(AuditLog.Action.VIEW_SENSITIVE, guest, property=request.property)
    from apps.reservations.models import Reservation

    stays = Reservation.objects.filter(guest=guest).select_related("room", "room_type", "property")[:50]
    duplicates = find_duplicates(
        doc_number=guest.doc_number, email=guest.email, phone=guest.phone, exclude_pk=guest.pk
    )[:5]
    history = AuditLog.objects.filter(object_type="guests.Guest", object_id=str(guest.pk))[:20]
    return render(
        request,
        "guests/guest_detail.html",
        {
            "guest": guest,
            "stays": stays,
            "duplicates": duplicates,
            "history": history,
            "show_sensitive": show_sensitive,
        },
    )


def _save(request, guest=None):
    is_new = guest is None
    guest = guest or Guest()
    before = {} if is_new else audit.snapshot(guest, AUDIT_FIELDS)
    form = GuestForm(request.POST or None, instance=guest)
    duplicates = []
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        duplicates = list(
            find_duplicates(
                doc_number=d.get("doc_number"),
                email=d.get("email"),
                phone=d.get("phone"),
                exclude_pk=guest.pk,
            )[:5]
        )
        if duplicates and not request.POST.get("confirm_duplicate"):
            messages.warning(
                request, _("Hay perfiles parecidos. Revise antes de crear uno nuevo (RF-HUE-02).")
            )
        else:
            with transaction.atomic():
                guest = form.save()
                if is_new:
                    audit.log(AuditLog.Action.CREATE, guest, property=request.property)
                else:
                    audit.log_changes(guest, before)
            messages.success(request, _("Huésped guardado."))
            next_url = request.GET.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(f"{next_url}{'&' if '?' in next_url else '?'}guest={guest.pk}")
            return redirect("guests:guest_detail", pk=guest.pk)
    return render(
        request,
        "guests/guest_form.html",
        {"form": form, "object": None if is_new else guest, "duplicates": duplicates},
    )


@require_perm("guests.create")
def guest_create(request):
    return _save(request)


@require_perm("guests.edit")
def guest_edit(request, pk):
    return _save(request, get_object_or_404(Guest, pk=pk))


@require_POST
@require_perm("guests.edit")
def guest_merge(request, pk):
    primary = get_object_or_404(Guest, pk=pk)
    duplicate = get_object_or_404(Guest, pk=request.POST.get("duplicate"))
    merge_guests(primary, duplicate)
    messages.success(request, _("Perfiles fusionados."))
    return redirect("guests:guest_detail", pk=primary.pk)


@require_POST
@require_perm("guests.void")
def guest_anonymize(request, pk):
    guest = get_object_or_404(Guest, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        raise PermissionDenied
    anonymize(guest, reason)
    messages.success(request, _("Datos personales eliminados (Ley 29733)."))
    return redirect("guests:guest_detail", pk=guest.pk)


# --------------------------------------------------------------------------
# Programa de fidelidad (RF-HUE-04)
# --------------------------------------------------------------------------

tier_crud = Crud(
    model=LoyaltyTier,
    module="guests",
    columns=[
        (gettext_lazy("Nivel"), "name"),
        (gettext_lazy("Desde (puntos)"), "min_points"),
        (gettext_lazy("Multiplicador"), "earn_multiplier"),
        (gettext_lazy("Descuento"), "discount_percent"),
        (gettext_lazy("Beneficios"), "benefits"),
    ],
    help_text=gettext_lazy("Niveles del programa de fidelidad (RF-HUE-04)."),
)


@require_perm("guests.view")
def guest_loyalty(request, pk):
    """Movimientos de puntos, nivel, canje en el folio y ajuste manual."""
    from apps.folio.models import Folio

    from . import loyalty

    guest = get_object_or_404(Guest, pk=pk)
    prop = request.property
    folios = Folio.objects.filter(
        property=prop, status="open", reservation__guest=guest, reservation__status="checked_in"
    )
    if request.method == "POST":
        try:
            points = int(request.POST.get("points") or 0)
            if request.POST.get("action") == "redeem":
                if not request.user.has_pms_perm(prop, "folio.create"):
                    raise PermissionDenied
                folio = get_object_or_404(folios, pk=request.POST.get("folio"))
                loyalty.redeem(guest, folio, points, request.user)
                messages.success(request, _("Puntos canjeados en el folio."))
            else:
                if not request.user.has_pms_perm(prop, "guests.approve"):
                    raise PermissionDenied
                loyalty.adjust(guest, prop, points, request.POST.get("reason", "").strip(), request.user)
                messages.success(request, _("Ajuste registrado."))
        except (ValueError, ValidationError) as exc:
            for m in getattr(exc, "messages", [str(exc)]):
                messages.error(request, m)
        return redirect("guests:guest_loyalty", pk=guest.pk)
    lifetime = loyalty.lifetime_points(guest)
    tiers = list(LoyaltyTier.objects.all())
    tier = next((t for t in reversed(tiers) if t.min_points <= lifetime), None)
    upcoming = next((t for t in tiers if t.min_points > lifetime), None)
    return render(
        request,
        "guests/loyalty.html",
        {
            "guest": guest,
            "lifetime": lifetime,
            "tier": tier,
            "next_tier": upcoming,
            "to_next": upcoming.min_points - lifetime if upcoming else 0,
            "value": loyalty.points_value(guest.loyalty_points),
            "folios": folios.select_related("reservation"),
            "moves": guest.loyalty_transactions.select_related("property", "reservation")[:50],
        },
    )
