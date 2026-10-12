from datetime import date

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.crud import Crud
from apps.core.models import AuditLog

from . import services
from .models import DocType, FakePerson, FakeTaxpayer, Invoice, Series, SimulationSettings, SunatSubmission
from .pdf import invoice_pdf_bytes
from .ple import ple_filename, sales_register
from .sunat import lookup_dni, lookup_ruc
from .validators import ruc_is_valid

series_crud = Crud(
    model=Series,
    module="billing",
    columns=[
        (gettext_lazy("Serie"), "code"),
        (gettext_lazy("Tipo"), "doc_type"),
        (gettext_lazy("Siguiente"), "next_number"),
        (gettext_lazy("Punto de venta"), "outlet"),
        (gettext_lazy("Activa"), "is_active"),
    ],
)
taxpayer_crud = Crud(
    model=FakeTaxpayer,
    module="billing",
    columns=[
        (gettext_lazy("RUC"), "ruc"),
        (gettext_lazy("Razón social"), "legal_name"),
        (gettext_lazy("Estado"), "status"),
        (gettext_lazy("Condición"), "condition"),
    ],
    search=["ruc", "legal_name"],
    help_text=gettext_lazy(
        "Padrón ficticio para la consulta RUC simulada (sección 12). Nunca use datos reales."
    ),
)
person_crud = Crud(
    model=FakePerson,
    module="billing",
    columns=[
        (gettext_lazy("DNI"), "dni"),
        (gettext_lazy("Nombres"), "first_name"),
        (gettext_lazy("Apellidos"), "last_name"),
    ],
    search=["dni", "last_name"],
    help_text=gettext_lazy("Padrón ficticio para la consulta DNI simulada (sección 12)."),
)

NC_REASONS = [
    ("01", "01 Anulación de la operación"),
    ("02", "02 Anulación por error en el RUC"),
    ("03", "03 Corrección por error en la descripción"),
    ("04", "04 Descuento global"),
    ("06", "06 Devolución total"),
    ("07", "07 Devolución por ítem"),
    ("13", "13 Ajustes - montos y/o fechas de pago"),
]
ND_REASONS = [("01", "01 Intereses por mora"), ("02", "02 Aumento en el valor"), ("03", "03 Penalidades")]


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


@require_perm("billing.view")
def invoice_list(request):
    qs = Invoice.objects.filter(property=request.property).select_related("series", "folio")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(customer_name__icontains=q) | Q(customer_doc__icontains=q) | Q(series__code__icontains=q)
        )
    for f in ("doc_type", "status"):
        if request.GET.get(f):
            qs = qs.filter(**{f: request.GET[f]})
    if request.GET.get("date"):
        qs = qs.filter(issue_date=request.GET["date"])
    totals = qs.exclude(status="voided").aggregate(total=Sum("total"), igv=Sum("igv"))
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    pending = Invoice.objects.filter(property=request.property, status="pending").count()
    return render(
        request,
        "billing/invoice_list.html",
        {
            "page": page,
            "q": q,
            "totals": totals,
            "pending": pending,
            "doc_types": DocType.choices,
            "statuses": Invoice.Status.choices,
        },
    )


@require_perm("billing.view")
def invoice_detail(request, pk):
    inv = get_object_or_404(
        Invoice.objects.select_related("series", "folio__reservation", "related_invoice"),
        pk=pk,
        property=request.property,
    )
    return render(
        request,
        "billing/invoice_detail.html",
        {
            "inv": inv,
            "lines": inv.lines.all(),
            "submissions": inv.submissions.all(),
            "notes": inv.notes.select_related("series"),
            "nc_reasons": NC_REASONS,
            "nd_reasons": ND_REASONS,
        },
    )


@require_perm("billing.view")
def invoice_pdf(request, pk):
    inv = get_object_or_404(Invoice, pk=pk, property=request.property)
    resp = HttpResponse(invoice_pdf_bytes(inv), content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'inline; filename="{request.property.ruc}-{inv.doc_type}-{inv.full_number}.pdf"'
    )
    return resp


@require_POST
@require_perm("billing.view")
def invoice_action(request, pk, action):
    inv = get_object_or_404(Invoice, pk=pk, property=request.property)
    try:
        if action == "send":
            services.send_invoice(inv)
            messages.info(request, f"{inv.get_status_display()}: {inv.sunat_message}")
        elif action == "email":
            to = request.POST.get("to") or inv.customer_email
            if not to:
                raise ValidationError(_("Indique un correo."))
            from apps.comms.services import send_message

            body = _("Adjuntamos su %(t)s %(n)s por %(c)s %(a)s. Gracias por su preferencia.") % {
                "t": inv.get_doc_type_display().lower(),
                "n": inv.full_number,
                "c": inv.currency,
                "a": inv.total,
            }
            msg = send_message(
                inv.property,
                "email",
                to,
                f"{inv.get_doc_type_display()} {inv.full_number}",
                body,
                reservation=inv.folio.reservation if inv.folio else None,
                event="invoice",
                attachments=[(f"{inv.full_number}.pdf", invoice_pdf_bytes(inv), "application/pdf")],
            )
            messages.success(
                request, _("Enviado a %(to)s (%(s)s).") % {"to": to, "s": msg.get_status_display()}
            )
        elif action == "credit_note":
            amount = request.POST.get("amount") or None
            note = services.credit_note(
                inv,
                request.POST.get("reason_code", "01"),
                request.POST.get("reason", ""),
                user=request.user,
                amount=amount,
            )
            messages.success(request, _("Nota de crédito %(n)s emitida.") % {"n": note.full_number})
            return redirect("billing:invoice_detail", pk=note.pk)
        elif action == "debit_note":
            note = services.debit_note(
                inv,
                request.POST.get("reason_code", "03"),
                request.POST.get("reason", ""),
                request.POST.get("amount") or "0",
                user=request.user,
            )
            return redirect("billing:invoice_detail", pk=note.pk)
        elif action == "void":
            services.void_invoice(inv, request.POST.get("reason", ""), user=request.user)
            messages.success(request, _("Comprobante dado de baja."))
    except (ValidationError, PermissionDenied) as exc:
        _errors(request, exc)
    return redirect("billing:invoice_detail", pk=inv.pk)


@require_POST
@require_perm("billing.create")
def retry_pending(request):
    n = services.retry_pending(request.property)
    messages.info(request, _("Reenviados: %(n)s aceptados.") % {"n": n})
    return redirect("billing:invoice_list")


@require_perm("billing.view")
def lookup(request):
    """Consulta RUC/DNI simulada (sección 12)."""
    ruc, dni = request.GET.get("ruc", "").strip(), request.GET.get("dni", "").strip()
    if ruc:
        if not ruc_is_valid(ruc):
            return JsonResponse({"found": False, "error": _("RUC inválido (dígito verificador).")})
        t = lookup_ruc(ruc)
        return JsonResponse(
            {
                "found": bool(t),
                "name": t.legal_name if t else "",
                "address": t.address if t else "",
                "status": t.status if t else "",
                "condition": t.condition if t else "",
            }
        )
    if dni:
        p = lookup_dni(dni)
        return JsonResponse({"found": bool(p), "name": f"{p.first_name} {p.last_name}" if p else ""})
    return JsonResponse({"found": False})


class SimulationForm(forms.ModelForm):
    class Meta:
        model = SimulationSettings
        fields = ["connection_down", "reject_next", "reject_message"]


@require_perm("billing.view")
def simulator(request):
    """Panel del docente: fallas de SUNAT para practicar (sección 12, RF-SIM-04)."""
    sim, _created = SimulationSettings.objects.get_or_create(property=request.property)
    form = SimulationForm(request.POST or None, instance=sim)
    if request.method == "POST":
        if not request.user.has_pms_perm(request.property, "billing.approve"):
            raise PermissionDenied
        if request.POST.get("summary"):
            sub = services.daily_summary(request.property, request.property.current_business_date())
            messages.info(request, sub.message)
            return redirect("billing:simulator")
        if form.is_valid():
            before = audit.snapshot(sim, ["connection_down", "reject_next"])
            form.save()
            audit.log_changes(sim, before, reason=_("Simulación SUNAT"))
            messages.success(request, _("Simulación actualizada."))
            return redirect("billing:simulator")
    return render(
        request,
        "billing/simulator.html",
        {
            "form": form,
            "submissions": SunatSubmission.objects.filter(property=request.property).select_related(
                "invoice__series"
            )[:40],
        },
    )


@require_perm("billing.export")
def ple_export(request):
    """RF-FAC-08: registro de ventas 14.1 (formato PLE, marcado como ejemplo)."""
    today = request.property.current_business_date()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    if request.GET.get("download"):
        content = sales_register(request.property, year, month)
        audit.log(
            AuditLog.Action.EXPORT, None, changes={"ple": f"{year}-{month:02d}"}, property=request.property
        )
        resp = HttpResponse(content, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="{ple_filename(request.property, year, month, bool(content))}"'
        )
        return resp
    start = date(year, month, 1)
    invoices = Invoice.objects.filter(
        property=request.property, issue_date__year=year, issue_date__month=month
    )
    summary = (
        invoices.exclude(status="voided")
        .values("doc_type")
        .annotate(
            n=Count("id"),
            total=Sum("total"),
            igv=Sum("igv"),
            taxed=Sum("taxed_amount"),
            export=Sum("export_amount"),
        )
    )
    return render(
        request,
        "billing/ple.html",
        {"year": year, "month": month, "start": start, "summary": summary, "count": invoices.count()},
    )
