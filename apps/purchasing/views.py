import csv
from datetime import date
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.core.models import Sequence
from apps.core.pdf import pdf_response
from apps.inventory.models import Item

from . import services
from .models import (
    PurchaseOrder,
    Quotation,
    QuotationLine,
    Requisition,
    RequisitionLine,
    Supplier,
    SupplierInvoice,
)


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


def _dec(v):
    try:
        return Decimal(str(v or "0").replace(",", ""))
    except InvalidOperation as exc:
        raise ValidationError(_("Número inválido.")) from exc


class SupplierForm(PropertyModelForm):
    class Meta:
        model = Supplier
        exclude = ["property", "created_by", "updated_by"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def clean_ruc(self):
        ruc = self.cleaned_data["ruc"].strip()
        services.validate_supplier_ruc(ruc)
        return ruc


supplier_crud = Crud(
    model=Supplier,
    module="purchasing",
    form_class=SupplierForm,
    columns=[
        (gettext_lazy("Proveedor"), "name"),
        (gettext_lazy("RUC"), "ruc"),
        (gettext_lazy("Contacto"), "contact_name"),
        (gettext_lazy("Días de pago"), "payment_days"),
        (gettext_lazy("Evaluación"), "rating"),
        (gettext_lazy("Activo"), "is_active"),
    ],
    search=["name", "ruc"],
    help_text=gettext_lazy("RUC validado con dígito verificador (RF-COM-04)."),
)

LineFormSet = forms.inlineformset_factory(
    Requisition, RequisitionLine, fields=["item", "quantity", "estimated_cost"], extra=4, can_delete=True
)


class RequisitionForm(PropertyModelForm):
    class Meta:
        model = Requisition
        fields = ["warehouse", "needed_by", "notes"]
        widgets = {
            "needed_by": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


@require_perm("purchasing.view")
def requisition_list(request):
    qs = (
        Requisition.objects.filter(property=request.property)
        .select_related("warehouse", "created_by")
        .prefetch_related("lines")
    )
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return render(
        request,
        "purchasing/requisition_list.html",
        {"items": qs[:100], "statuses": Requisition.Status.choices},
    )


@require_perm("purchasing.create")
def requisition_create(request, pk=None):
    """RF-COM-01: requisición interna por área."""
    prop = request.property
    req = get_object_or_404(Requisition, pk=pk, property=prop) if pk else Requisition(property=prop)
    if pk and req.status != Requisition.Status.DRAFT:
        return redirect("purchasing:requisition_detail", pk=req.pk)
    form = RequisitionForm(request.POST or None, instance=req, property=prop)
    initial = []
    if not pk and request.GET.get("sugerido"):
        from apps.inventory.services import suggested_orders

        initial = [
            {"item": s["item"].pk, "quantity": s["need"], "estimated_cost": s["item"].last_cost}
            for s in suggested_orders(prop)
        ]
    formset = LineFormSet(request.POST or None, instance=req, prefix="lines", initial=initial or None)
    if initial:
        formset.extra = max(len(initial), 1)
    for f in formset.forms:
        f.fields["item"].queryset = Item.objects.filter(property=prop, is_active=True)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            req = form.save(commit=False)
            req.property = prop
            if not req.number:
                req.number = f"RQ{Sequence.next_value(prop, 'requisition'):05d}"
            req.save()
            formset.instance = req
            formset.save()
        if request.POST.get("submit"):
            try:
                services.submit(req, request.user)
                messages.success(request, _("Requisición enviada a aprobación."))
            except ValidationError as exc:
                _errors(request, exc)
        return redirect("purchasing:requisition_detail", pk=req.pk)
    return render(
        request,
        "purchasing/requisition_form.html",
        {"form": form, "formset": formset, "object": req if pk else None},
    )


class QuotationForm(forms.Form):
    supplier = forms.ModelChoiceField(label=gettext_lazy("Proveedor"), queryset=Supplier.objects.none())
    delivery_days = forms.IntegerField(label=gettext_lazy("Días de entrega"), min_value=0, initial=2)
    notes = forms.CharField(label=gettext_lazy("Condiciones"), required=False)


@require_perm("purchasing.view")
def requisition_detail(request, pk):
    """RF-COM-01/02: aprobación por monto y cotizaciones comparativas."""
    prop = request.property
    req = get_object_or_404(
        Requisition.objects.select_related("warehouse", "approved_by"), pk=pk, property=prop
    )
    lines = list(req.lines.select_related("item"))
    qform = QuotationForm(request.POST or None)
    qform.fields["supplier"].queryset = Supplier.objects.filter(property=prop, is_active=True)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action in ("approve", "reject"):
                services.decide(req, request.user, action == "approve", request.POST.get("reason", ""))
                messages.success(request, _("Requisición %(s)s.") % {"s": req.get_status_display().lower()})
            elif action == "submit":
                services.submit(req, request.user)
            elif action == "quote" and qform.is_valid():
                if not request.user.has_pms_perm(prop, "purchasing.create"):
                    raise PermissionDenied
                with transaction.atomic():
                    q = Quotation.objects.create(
                        requisition=req,
                        supplier=qform.cleaned_data["supplier"],
                        delivery_days=qform.cleaned_data["delivery_days"],
                        notes=qform.cleaned_data["notes"],
                    )
                    for ln in lines:
                        price = request.POST.get(f"price-{ln.pk}")
                        if price:
                            QuotationLine.objects.create(
                                quotation=q, item=ln.item, quantity=ln.quantity, unit_price=_dec(price)
                            )
                messages.success(request, _("Cotización registrada."))
            elif action == "order":
                q = get_object_or_404(Quotation, pk=request.POST.get("quotation"), requisition=req)
                po = services.order_from_quotation(q, request.user)
                messages.success(request, _("Orden de compra %(n)s emitida.") % {"n": po.number})
                return redirect("purchasing:po_detail", pk=po.pk)
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
        return redirect("purchasing:requisition_detail", pk=req.pk)
    quotes = list(req.quotations.select_related("supplier").prefetch_related("lines"))
    best = min(quotes, key=lambda q: q.total) if quotes else None
    compare = []
    for ln in lines:
        prices = []
        for q in quotes:
            match = next((x for x in q.lines.all() if x.item_id == ln.item_id), None)
            prices.append(match.unit_price if match else None)
        valid = [p for p in prices if p is not None]
        compare.append({"line": ln, "prices": prices, "min": min(valid) if valid else None})
    return render(
        request,
        "purchasing/requisition_detail.html",
        {
            "req": req,
            "lines": lines,
            "quotes": quotes,
            "best": best,
            "compare": compare,
            "qform": qform,
            "can_approve": services.can_approve(request.user, prop, req.estimated_total),
        },
    )


@require_perm("purchasing.view")
def po_list(request):
    qs = (
        PurchaseOrder.objects.filter(property=request.property)
        .select_related("supplier", "warehouse")
        .prefetch_related("lines")
    )
    return render(request, "purchasing/po_list.html", {"items": qs[:100]})


@require_perm("purchasing.view")
def po_detail(request, pk):
    """RF-COM-03: recepción parcial o total contra la orden de compra."""
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier", "warehouse"), pk=pk, property=request.property
    )
    lines = list(po.lines.select_related("item"))
    if request.method == "POST":
        if not request.user.has_pms_perm(
            request.property, "inventory.create"
        ) and not request.user.has_pms_perm(request.property, "purchasing.edit"):
            raise PermissionDenied
        try:
            if request.POST.get("action") == "receive":
                quantities = {ln.pk: _dec(request.POST.get(f"qty-{ln.pk}")) for ln in lines}
                lots = {}
                for ln in lines:
                    exp = request.POST.get(f"exp-{ln.pk}")
                    if request.POST.get(f"lot-{ln.pk}") or exp:
                        lots[ln.pk] = (
                            request.POST.get(f"lot-{ln.pk}", ""),
                            date.fromisoformat(exp) if exp else None,
                        )
                services.receive_goods(
                    po,
                    quantities,
                    user=request.user,
                    guide=request.POST.get("guide", ""),
                    invoice=request.POST.get("invoice", ""),
                    lots=lots,
                )
                messages.success(request, _("Mercadería ingresada al almacén."))
            elif request.POST.get("action") == "invoice":
                services.register_invoice(
                    po, request.POST.get("number", ""), _dec(request.POST.get("amount"))
                )
                messages.success(request, _("Factura registrada en cuentas por pagar."))
            elif request.POST.get("action") == "cancel":
                po.status = PurchaseOrder.Status.CANCELLED
                po.save(update_fields=["status"])
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
        return redirect("purchasing:po_detail", pk=po.pk)
    return render(
        request,
        "purchasing/po_detail.html",
        {
            "po": po,
            "lines": lines,
            "receipts": po.receipts.all(),
            "invoices": SupplierInvoice.objects.filter(order=po),
            "igv": (po.total * Decimal("0.18")).quantize(Decimal("0.01")),
        },
    )


@require_perm("purchasing.view")
def po_pdf(request, pk):
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier", "warehouse"), pk=pk, property=request.property
    )
    igv = (po.total * Decimal("0.18")).quantize(Decimal("0.01"))
    return pdf_response(
        "purchasing/po_pdf.html",
        {
            "po": po,
            "lines": po.lines.select_related("item"),
            "property": po.property,
            "igv": igv,
            "total": po.total + igv,
        },
        f"{po.number}.pdf",
    )


@require_perm("purchasing.view")
def payables(request):
    """RF-COM-05: cuentas por pagar con vencimientos y exportación a contabilidad."""
    prop = request.property
    qs = SupplierInvoice.objects.filter(property=prop).select_related("supplier", "order")
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "purchasing.edit"):
            raise PermissionDenied
        inv = get_object_or_404(SupplierInvoice, pk=request.POST.get("invoice"), property=prop)
        inv.paid = True
        inv.paid_at = prop.current_business_date()
        inv.save(update_fields=["paid", "paid_at"])
        return redirect("purchasing:payables")
    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="cuentas-por-pagar.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["RUC", "Proveedor", "Factura", "Emisión", "Vencimiento", "Importe", "Pagada"])
        for i in qs:
            w.writerow(
                [
                    i.supplier.ruc,
                    i.supplier.name,
                    i.number,
                    i.issue_date,
                    i.due_date,
                    i.amount,
                    "Sí" if i.paid else "No",
                ]
            )
        return resp
    return render(
        request,
        "purchasing/payables.html",
        {
            "items": qs,
            "today": prop.current_business_date(),
            "pending": sum((i.amount for i in qs if not i.paid), Decimal("0")),
        },
    )
