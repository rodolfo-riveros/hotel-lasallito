from django.contrib import messages
from django.core.exceptions import PermissionDenied
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
from .models import Company, Guest
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
