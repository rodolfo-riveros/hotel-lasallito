import csv
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.decorators import require_perm

from . import audit
from .forms import AuditFilterForm, ExchangeRateForm, PropertyForm, TaxRuleForm
from .models import AuditLog, ExchangeRate, TaxRule
from .status import GROUPS


def _require_property(request):
    if request.property is None:
        raise PermissionDenied(_("No tienes acceso a ninguna propiedad."))
    return request.property


@require_perm("dashboard.view")
def dashboard(request):
    """Tablero gerencial. En la fase 0 muestra la estructura; los indicadores
    reales (ocupación, ADR, RevPAR) se calculan desde la fase 1 (RF-REP-01)."""
    today = timezone.localdate()
    usd = ExchangeRate.for_date("USD", today)
    kpis = [
        {"label": _("Ocupación"), "value": "—", "hint": _("Fase 1"), "icon": "bed"},
        {"label": _("ADR"), "value": "—", "hint": _("Tarifa promedio"), "icon": "tag"},
        {"label": _("RevPAR"), "value": "—", "hint": _("Ingreso por habitación disponible"), "icon": "chart"},
        {"label": _("Llegadas hoy"), "value": "—", "hint": _("Fase 1"), "icon": "key"},
    ]
    recent = AuditLog.objects.filter(property=request.property).select_related("user")[:8]
    if not request.user.has_pms_perm(request.property, "audit.view"):
        recent = []
    return render(
        request,
        "core/dashboard.html",
        {
            "today": today,
            "usd_rate": usd,
            "kpis": kpis,
            "recent_activity": recent,
        },
    )


# --------------------------------------------------------------------------
# Configuración de la propiedad
# --------------------------------------------------------------------------

PROPERTY_AUDIT_FIELDS = [
    "name",
    "legal_name",
    "ruc",
    "address",
    "phone",
    "email",
    "check_in_time",
    "check_out_time",
    "brand_color",
    "base_currency",
]


@require_perm("settings.view")
def property_settings(request):
    prop = _require_property(request)
    can_edit = request.user.has_pms_perm(prop, "settings.edit")
    before = audit.snapshot(prop, PROPERTY_AUDIT_FIELDS)
    form = PropertyForm(request.POST or None, request.FILES or None, instance=prop)
    if not can_edit:
        for field in form.fields.values():
            field.disabled = True
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            with transaction.atomic():
                form.save()
                audit.log_changes(prop, before)
            messages.success(request, _("Configuración guardada."))
            return redirect("core:property_settings")
    return render(request, "core/property_settings.html", {"form": form, "can_edit": can_edit})


# --------------------------------------------------------------------------
# Tipo de cambio (RF-TAR-03)
# --------------------------------------------------------------------------


@require_perm("settings.view")
def exchange_rates(request):
    can_edit = request.user.has_pms_perm(request.property, "settings.edit")
    form = ExchangeRateForm(request.POST or None, initial={"date": timezone.localdate(), "currency": "USD"})
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                existing = ExchangeRate.objects.filter(date=data["date"], currency=data["currency"]).first()
                if existing:
                    before = audit.snapshot(existing, ["buy", "sell"])
                    existing.buy, existing.sell = data["buy"], data["sell"]
                    existing.save()
                    audit.log_changes(existing, before, action=AuditLog.Action.RATE_CHANGE)
                else:
                    rate = ExchangeRate.objects.create(**data)
                    audit.log(AuditLog.Action.CREATE, rate, property=request.property)
            messages.success(request, _("Tipo de cambio registrado."))
            return redirect("core:exchange_rates")
    since = timezone.localdate() - timedelta(days=60)
    rates = ExchangeRate.objects.filter(date__gte=since).select_related("currency", "updated_by")
    return render(request, "core/exchange_rates.html", {"form": form, "rates": rates, "can_edit": can_edit})


# --------------------------------------------------------------------------
# Impuestos (RF-TAR-06)
# --------------------------------------------------------------------------

TAX_AUDIT_FIELDS = ["code", "name", "rate", "applies_to", "exempt_for_non_domiciled", "is_active"]


@require_perm("settings.view")
def tax_list(request):
    prop = _require_property(request)
    taxes = TaxRule.objects.filter(property=prop)
    can_edit = request.user.has_pms_perm(prop, "settings.edit")
    return render(request, "core/tax_list.html", {"taxes": taxes, "can_edit": can_edit})


@require_perm("settings.edit")
def tax_edit(request, pk=None):
    prop = _require_property(request)
    tax = get_object_or_404(TaxRule, pk=pk, property=prop) if pk else TaxRule(property=prop)
    before = audit.snapshot(tax, TAX_AUDIT_FIELDS) if pk else {}
    form = TaxRuleForm(request.POST or None, instance=tax)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save()
            if pk:
                audit.log_changes(saved, before, action=AuditLog.Action.RATE_CHANGE)
            else:
                audit.log(AuditLog.Action.CREATE, saved)
        messages.success(request, _("Impuesto guardado."))
        return redirect("core:tax_list")
    return render(request, "core/tax_form.html", {"form": form, "object": tax if pk else None})


# --------------------------------------------------------------------------
# Auditoría (RNF-SEG-03)
# --------------------------------------------------------------------------


@require_perm("audit.view")
def audit_list(request):
    form = AuditFilterForm(request.GET or None)
    logs = AuditLog.objects.select_related("user", "property")
    if not request.user.is_superuser:
        logs = logs.filter(property=request.property)
    if form.is_valid():
        data = form.cleaned_data
        if data.get("action"):
            logs = logs.filter(action=data["action"])
        if data.get("user"):
            logs = logs.filter(username__icontains=data["user"])
        if data.get("date_from"):
            logs = logs.filter(timestamp__date__gte=data["date_from"])
        if data.get("date_to"):
            logs = logs.filter(timestamp__date__lte=data["date_to"])
        if data.get("q"):
            logs = logs.filter(object_repr__icontains=data["q"])

    if request.GET.get("export") == "csv":
        if not request.user.has_pms_perm(request.property, "audit.export"):
            raise PermissionDenied
        audit.log(AuditLog.Action.EXPORT, None, changes={"reporte": "auditoria"}, property=request.property)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="auditoria.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(["fecha", "usuario", "accion", "objeto", "cambios", "motivo", "ip"])
        for log in logs[:5000]:
            writer.writerow(
                [
                    timezone.localtime(log.timestamp).strftime("%d/%m/%Y %H:%M:%S"),
                    log.username,
                    log.get_action_display(),
                    log.object_repr,
                    log.changes,
                    log.reason,
                    log.ip_address or "",
                ]
            )
        return response

    page = Paginator(logs, 25).get_page(request.GET.get("page"))
    return render(request, "core/audit_list.html", {"form": form, "page": page})


# --------------------------------------------------------------------------
# Guía visual (para aprobar el diseño base, fase 0)
# --------------------------------------------------------------------------


@require_perm("dashboard.view")
def design_system(request):
    return render(request, "core/design_system.html", {"status_groups": GROUPS})


@require_perm("dashboard.view")
def offline(request):
    return render(request, "core/offline.html")
