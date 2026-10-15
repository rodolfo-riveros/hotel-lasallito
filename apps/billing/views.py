from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.crud import Crud
from apps.core.models import AuditLog

from . import services, ubl
from .models import (
    CustomerDocType,
    DocType,
    FakePerson,
    FakeTaxpayer,
    Invoice,
    RemissionGuide,
    RemissionLine,
    Series,
    SunatRegistry,
    SunatSubmission,
    SunatTicket,
)
from .pdf import guide_pdf_bytes, invoice_pdf_bytes
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
        "Padrón ficticio para la consulta RUC simulada (sección 12). Nunca use datos reales. Un RUC "
        "válido que no figure aquí se considera ACTIVO y HABIDO."
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
    totals = qs.exclude(status__in=["voided", "rejected"]).aggregate(total=Sum("total"), igv=Sum("igv"))
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
            "doc_types": [(k, v) for k, v in DocType.choices if k != DocType.REMISSION],
            "statuses": Invoice.Status.choices,
        },
    )


def _invoice(request, pk):
    return get_object_or_404(
        Invoice.objects.select_related("series", "folio__reservation", "related_invoice__series", "property"),
        pk=pk,
        property=request.property,
    )


@require_perm("billing.view")
def invoice_detail(request, pk):
    inv = _invoice(request, pk)
    return render(
        request,
        "billing/invoice_detail.html",
        {
            "inv": inv,
            "lines": inv.lines.all(),
            "submissions": inv.submissions.all(),
            "notes": inv.notes.select_related("series"),
            "advances": inv.advances.select_related("series"),
            "nc_reasons": NC_REASONS,
            "nd_reasons": ND_REASONS,
        },
    )


@require_perm("billing.view")
def invoice_pdf(request, pk):
    inv = _invoice(request, pk)
    resp = HttpResponse(invoice_pdf_bytes(inv), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{inv.file_name}.pdf"'
    return resp


@require_perm("billing.view")
def invoice_file(request, pk, kind):
    """Descarga el XML firmado o la constancia de recepción (CDR) comprimida, como en SUNAT."""
    inv = _invoice(request, pk)
    if kind == "xml" and inv.xml:
        resp = HttpResponse(inv.xml, content_type="application/xml; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{inv.file_name}.xml"'
        return resp
    if kind == "cdr" and inv.cdr_xml:
        resp = HttpResponse(
            ubl.zip_bytes(f"R-{inv.file_name}.xml", inv.cdr_xml), content_type="application/zip"
        )
        resp["Content-Disposition"] = f'attachment; filename="R-{inv.file_name}.zip"'
        return resp
    raise Http404


@require_POST
@require_perm("billing.view")
def invoice_action(request, pk, action):
    inv = _invoice(request, pk)
    try:
        if action == "send":
            services.send_invoice(inv)
            messages.info(request, f"{inv.get_status_display()}: {inv.sunat_code} {inv.sunat_message}")
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
            files = [(f"{inv.file_name}.pdf", invoice_pdf_bytes(inv), "application/pdf")]
            if inv.xml:
                files.append((f"{inv.file_name}.xml", inv.xml.encode(), "application/xml"))
            msg = send_message(
                inv.property,
                "email",
                to,
                f"{inv.get_doc_type_display()} {inv.full_number}",
                body,
                reservation=inv.folio.reservation if inv.folio else None,
                event="invoice",
                attachments=files,
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
            inv.refresh_from_db()
            if inv.status == Invoice.Status.VOIDED:
                messages.success(request, _("Comprobante dado de baja."))
            else:
                messages.info(request, _("Baja enviada a SUNAT. El ticket se procesa en unos segundos."))
        elif action == "ticket":
            sub = inv.submissions.exclude(ticket="").first()
            if sub:
                result = services.check_ticket(sub.ticket)
                messages.info(request, f"{result.code} {result.message}")
    except (ValidationError, PermissionDenied) as exc:
        _errors(request, exc)
    return redirect("billing:invoice_detail", pk=inv.pk)


@require_POST
@require_perm("billing.create")
def retry_pending(request):
    n = services.retry_pending(request.property)
    services.poll_tickets(request.property)
    messages.info(request, _("Reenviados: %(n)s respondidos por SUNAT.") % {"n": n})
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


@require_perm("billing.view")
def sunat_panel(request):
    """Monitor de la SUNAT simulada: envíos, tickets, comprobantes registrados y resumen diario."""
    prop = request.property
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "billing.create"):
            raise PermissionDenied
        if request.POST.get("summary"):
            sub = services.daily_summary(prop, prop.current_business_date())
            messages.info(request, f"{sub.code} {sub.message}")
        elif request.POST.get("poll"):
            n = services.poll_tickets(prop)
            messages.info(request, _("Tickets procesados: %(n)s.") % {"n": n})
        return redirect("billing:sunat")
    registry = SunatRegistry.objects.filter(issuer_ruc=prop.ruc).order_by("-received_at")
    stats = registry.values("status").annotate(n=Count("pk"))
    return render(
        request,
        "billing/sunat.html",
        {
            "submissions": SunatSubmission.objects.filter(property=prop).select_related("invoice__series")[
                :30
            ],
            "tickets": SunatTicket.objects.filter(property=prop)[:20],
            "registry": registry[:20],
            "stats": {r["status"]: r["n"] for r in stats},
        },
    )


@require_perm("billing.view")
def ticket_cdr(request, number):
    t = get_object_or_404(SunatTicket, number=number, property=request.property)
    if not t.cdr_xml:
        raise Http404
    resp = HttpResponse(ubl.zip_bytes(f"R-{t.file_name}.xml", t.cdr_xml), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="R-{t.file_name}.zip"'
    return resp


def validity_check(request):
    """Consulta pública de validez del comprobante, como la de SUNAT (sin iniciar sesión)."""
    result = None
    data = request.GET
    if data.get("ruc") and data.get("serie") and data.get("numero"):
        try:
            number = int(data["numero"])
        except ValueError:
            number = -1
        reg = SunatRegistry.objects.filter(
            issuer_ruc=data["ruc"].strip(),
            doc_type=data.get("tipo", "01"),
            series=data["serie"].strip().upper(),
            number=number,
        ).first()
        if reg is None:
            result = {"ok": False, "text": _("El comprobante no ha sido informado a SUNAT.")}
        else:
            total_ok = not data.get("total") or _same_amount(data["total"], reg.total)
            date_ok = not data.get("fecha") or data["fecha"] == reg.issue_date.isoformat()
            if not (total_ok and date_ok):
                result = {
                    "ok": False,
                    "text": _("Los datos ingresados no coinciden con el comprobante informado."),
                }
            elif reg.status == SunatRegistry.Status.VOIDED:
                result = {"ok": False, "text": _("El comprobante fue comunicado de baja: NO es válido.")}
            else:
                result = {
                    "ok": True,
                    "reg": reg,
                    "text": _("El comprobante es válido: fue informado a SUNAT (simulada)."),
                }
    return render(
        request, "billing/validity.html", {"result": result, "data": data, "doc_types": DocType.choices}
    )


def _same_amount(text, amount):
    try:
        return abs(float(text) - float(amount)) < 0.01
    except ValueError:
        return False


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
        invoices.exclude(status__in=["voided", "rejected"])
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


# --------------------------------------------------------------------------
# RF-FAC-06: facturación agrupada (empresas y agencias) y anticipos
# --------------------------------------------------------------------------


class GroupedForm(forms.Form):
    company = forms.ModelChoiceField(label=gettext_lazy("Empresa o agencia"), queryset=None)
    start = forms.DateField(
        label=gettext_lazy("Consumos desde"), widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(
        label=gettext_lazy("Hasta (inclusive)"), widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.guests.models import Company

        self.fields["company"].queryset = Company.objects.exclude(ruc="").order_by("legal_name")


@require_perm("billing.create")
def grouped(request):
    """Una factura a crédito con los consumos de varias estadías de una empresa o agencia."""
    prop = request.property
    today = prop.current_business_date()
    first = today.replace(day=1)
    form = GroupedForm(
        request.GET or None,
        initial={"start": (first - timedelta(days=1)).replace(day=1), "end": first - timedelta(days=1)},
    )
    charges, company, total = [], None, 0
    if form.is_valid():
        company = form.cleaned_data["company"]
        charges = list(
            services.grouped_charges(
                prop, company, form.cleaned_data["start"], form.cleaned_data["end"] + timedelta(days=1)
            )
        )
        total = sum(c.amount for c in charges)
    if request.method == "POST":
        company = get_object_or_404(form.fields["company"].queryset, pk=request.POST.get("company"))
        ids = request.POST.getlist("charges")
        try:
            inv = services.issue_grouped_invoice(
                prop,
                company,
                [
                    c
                    for c in services.grouped_charges(prop, company, date(2000, 1, 1), date(2100, 1, 1))
                    if str(c.pk) in ids
                ],
                user=request.user,
                currency=request.POST.get("currency", "PEN"),
            )
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
            return redirect(request.get_full_path())
        messages.success(
            request, _("Factura %(n)s emitida por %(c)s.") % {"n": inv.full_number, "c": inv.total}
        )
        return redirect("billing:invoice_detail", pk=inv.pk)
    return render(
        request,
        "billing/grouped.html",
        {"form": form, "charges": charges, "company": company, "total": total},
    )


class AdvanceForm(forms.Form):
    doc_type = forms.ChoiceField(
        label=gettext_lazy("Comprobante"),
        choices=[(DocType.BOLETA, _("Boleta")), (DocType.FACTURA, _("Factura"))],
    )
    customer_doc_type = forms.ChoiceField(
        label=gettext_lazy("Tipo de documento"), choices=CustomerDocType.choices
    )
    customer_doc = forms.CharField(label=gettext_lazy("N.° de documento"), required=False)
    customer_name = forms.CharField(label=gettext_lazy("Nombre / razón social"))
    customer_address = forms.CharField(label=gettext_lazy("Dirección"), required=False)
    amount = forms.DecimalField(label=gettext_lazy("Monto del anticipo"), min_value=0, decimal_places=2)
    currency = forms.ChoiceField(label=gettext_lazy("Moneda"), choices=[("PEN", "PEN"), ("USD", "USD")])


@require_perm("billing.create")
def advance(request, folio_pk):
    """RF-FAC-06: comprobante por el adelanto de una reserva; se descuenta en el comprobante final."""
    from apps.folio.models import Folio

    folio = get_object_or_404(
        Folio.objects.select_related("reservation__guest", "company"), pk=folio_pk, property=request.property
    )
    available = services.deposits_available(folio)
    doc = (
        DocType.FACTURA
        if (folio.company or (folio.reservation and folio.reservation.company))
        else DocType.BOLETA
    )
    c = services.customer_from_folio(folio, doc)
    form = AdvanceForm(
        request.POST or None,
        initial={
            "doc_type": doc,
            "customer_doc_type": c.doc_type,
            "customer_doc": c.doc,
            "customer_name": c.name,
            "customer_address": c.address,
            "amount": available,
            "currency": "PEN",
        },
    )
    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data
        customer = services.Customer(
            cd["customer_doc_type"],
            cd["customer_doc"].strip(),
            cd["customer_name"],
            cd["customer_address"],
            c.email,
            c.company,
        )
        try:
            inv = services.issue_advance(
                folio, cd["doc_type"], customer, cd["amount"], user=request.user, currency=cd["currency"]
            )
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
        else:
            messages.success(request, _("Comprobante de anticipo %(n)s emitido.") % {"n": inv.full_number})
            return redirect("billing:invoice_detail", pk=inv.pk)
    return render(
        request,
        "core/simple_form.html",
        {
            "form": form,
            "title": _("Comprobante de anticipo · folio %(n)s") % {"n": folio.number},
            "subtitle": _(
                "Adelantos cobrados sin comprobante: S/ %(a)s. Se descontará en la boleta o factura final."
            )
            % {"a": available},
            "back": f"/folios/{folio.pk}/",
            "submit": _("Emitir anticipo"),
        },
    )


# --------------------------------------------------------------------------
# RF-FAC-09: guía de remisión electrónica remitente
# --------------------------------------------------------------------------


class GuideForm(forms.ModelForm):
    supplier = forms.ModelChoiceField(
        label=gettext_lazy("Completar destinatario desde proveedor"), queryset=None, required=False
    )

    class Meta:
        model = RemissionGuide
        fields = [
            "reason",
            "reason_detail",
            "transfer_date",
            "supplier",
            "recipient_doc_type",
            "recipient_doc",
            "recipient_name",
            "origin_address",
            "origin_ubigeo",
            "destination_address",
            "destination_ubigeo",
            "gross_weight",
            "packages",
            "transport_mode",
            "carrier_ruc",
            "carrier_name",
            "vehicle_plate",
            "driver_doc",
            "driver_name",
            "driver_license",
            "notes",
        ]
        widgets = {"transfer_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, property_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.purchasing.models import Supplier

        self.fields["supplier"].queryset = Supplier.objects.filter(property=property_obj, is_active=True)
        self.fields["recipient_doc"].required = False
        self.fields["recipient_name"].required = False

    def clean(self):
        cd = super().clean()
        sup = cd.get("supplier")
        if sup:
            cd["recipient_doc_type"], cd["recipient_doc"], cd["recipient_name"] = "6", sup.ruc, sup.name
            if not cd.get("destination_address") and sup.address:
                cd["destination_address"] = sup.address
        if not cd.get("recipient_doc") or not cd.get("recipient_name"):
            raise ValidationError(_("Indique el destinatario (o elija un proveedor)."))
        return cd


LineFormSet = forms.inlineformset_factory(
    RemissionGuide,
    RemissionLine,
    fields=["item", "description", "unit", "quantity"],
    extra=4,
    can_delete=True,
)


@require_perm("billing.view")
def guide_list(request):
    guides = RemissionGuide.objects.filter(property=request.property).select_related("series")
    return render(request, "billing/guide_list.html", {"guides": guides[:100]})


@require_perm("billing.create")
def guide_edit(request, pk=None):
    prop = request.property
    guide = get_object_or_404(RemissionGuide, pk=pk, property=prop) if pk else services.new_guide(prop)
    if guide.pk and guide.status not in ("draft", "rejected"):
        messages.info(request, _("La guía ya fue enviada a SUNAT."))
        return redirect("billing:guide_detail", pk=guide.pk)
    form = GuideForm(request.POST or None, instance=guide, property_obj=prop)
    formset = LineFormSet(request.POST or None, instance=guide, prefix="l")
    from apps.inventory.models import Item

    for f in formset.forms:
        f.fields["item"].queryset = Item.objects.filter(property=prop, is_active=True)
        f.fields["item"].required = False
        f.fields["description"].required = False
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        for k in ("recipient_doc_type", "recipient_doc", "recipient_name", "destination_address"):
            setattr(guide, k, form.cleaned_data.get(k) or getattr(guide, k))
        guide = form.save()
        for f in formset.forms:
            if f.cleaned_data.get("item") and not f.cleaned_data.get("description"):
                f.instance.description = f.cleaned_data["item"].name
                f.instance.code = (
                    f.cleaned_data["item"].code if hasattr(f.cleaned_data["item"], "code") else ""
                )
        lines = formset.save(commit=False)
        for ln in lines:
            if ln.description and ln.quantity:
                ln.guide = guide
                ln.save()
        for obj in formset.deleted_objects:
            obj.delete()
        if request.POST.get("send"):
            try:
                services.issue_guide(guide, user=request.user)
                messages.success(request, _("Guía enviada a SUNAT. El ticket se procesa en unos segundos."))
            except (ValidationError, PermissionDenied) as exc:
                _errors(request, exc)
        return redirect("billing:guide_detail", pk=guide.pk)
    return render(request, "billing/guide_form.html", {"form": form, "formset": formset, "guide": guide})


@require_perm("billing.view")
def guide_detail(request, pk):
    guide = get_object_or_404(
        RemissionGuide.objects.select_related("series", "ticket"), pk=pk, property=request.property
    )
    if request.method == "POST":
        if not request.user.has_pms_perm(request.property, "billing.create"):
            raise PermissionDenied
        try:
            if request.POST.get("send"):
                services.issue_guide(guide, user=request.user)
            elif request.POST.get("ticket") and guide.ticket:
                r = services.check_ticket(guide.ticket.number)
                messages.info(request, f"{r.code} {r.message}")
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
        return redirect("billing:guide_detail", pk=guide.pk)
    return render(request, "billing/guide_detail.html", {"g": guide, "lines": guide.lines.all()})


@require_perm("billing.view")
def guide_file(request, pk, kind):
    g = get_object_or_404(RemissionGuide, pk=pk, property=request.property)
    if kind == "pdf" and g.number:
        resp = HttpResponse(guide_pdf_bytes(g), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{g.file_name}.pdf"'
        return resp
    if kind == "xml" and g.xml:
        resp = HttpResponse(g.xml, content_type="application/xml; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{g.file_name}.xml"'
        return resp
    if kind == "cdr" and g.cdr_xml:
        resp = HttpResponse(ubl.zip_bytes(f"R-{g.file_name}.xml", g.cdr_xml), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="R-{g.file_name}.zip"'
        return resp
    raise Http404
