from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.billing import services as billing
from apps.billing.models import CustomerDocType, DocType, Invoice
from apps.core.crud import Crud, PropertyModelForm

from . import services
from .models import CashRegister, CashSession, Charge, Concept, Folio, Payment

concept_crud = Crud(
    model=Concept,
    module="folio",
    columns=[
        (gettext_lazy("Código"), "code"),
        (gettext_lazy("Nombre"), "name"),
        (gettext_lazy("Categoría"), "category"),
        (gettext_lazy("Precio sugerido"), "default_price"),
        (gettext_lazy("Afecto IGV"), "is_taxable"),
        (gettext_lazy("Activo"), "is_active"),
    ],
    search=["code", "name"],
    filters=["category"],
)
register_crud = Crud(
    model=CashRegister,
    module="folio",
    columns=[(gettext_lazy("Caja"), "name"), (gettext_lazy("Activa"), "is_active")],
)


def _errors(request, exc):
    for msg in getattr(exc, "messages", [str(exc)]):
        messages.error(request, msg)


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except InvalidOperation as exc:
        raise ValidationError(_("Monto inválido.")) from exc


class ChargeForm(forms.Form):
    concept = forms.ModelChoiceField(label=gettext_lazy("Concepto"), queryset=Concept.objects.none())
    description = forms.CharField(label=gettext_lazy("Descripción"), required=False)
    quantity = forms.DecimalField(label=gettext_lazy("Cantidad"), initial=1, min_value=Decimal("0.001"))
    unit_price = forms.DecimalField(label=gettext_lazy("Precio unitario (incluye IGV)"), min_value=0)
    discount_percent = forms.DecimalField(
        label=gettext_lazy("Descuento %"), initial=0, min_value=0, max_value=100, required=False
    )


class PaymentForm(forms.Form):
    method = forms.ChoiceField(label=gettext_lazy("Medio de pago"), choices=Payment.Method.choices)
    amount = forms.DecimalField(label=gettext_lazy("Monto"), min_value=Decimal("0.01"))
    reference = forms.CharField(label=gettext_lazy("N.° de operación / voucher"), required=False)
    is_deposit = forms.BooleanField(label=gettext_lazy("Adelanto / depósito"), required=False)
    refund = forms.BooleanField(label=gettext_lazy("Es una devolución"), required=False)


class InvoiceForm(forms.Form):
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
    customer_email = forms.EmailField(label=gettext_lazy("Correo para enviar"), required=False)
    currency = forms.ChoiceField(label=gettext_lazy("Moneda"), choices=[("PEN", "PEN"), ("USD", "USD")])
    credit_days = forms.IntegerField(
        label=gettext_lazy("Días de crédito"), min_value=0, initial=0, required=False
    )


def _get(request, pk) -> Folio:
    return get_object_or_404(
        Folio.objects.select_related("reservation__guest", "reservation__room", "guest", "company"),
        pk=pk,
        property=request.property,
    )


@require_perm("folio.view")
def folio_detail(request, pk):
    folio = _get(request, pk)
    charge_form = ChargeForm(prefix="c")
    charge_form.fields["concept"].queryset = Concept.objects.filter(property=request.property, is_active=True)
    customer = billing.customer_from_folio(folio, DocType.BOLETA)
    invoice_form = InvoiceForm(
        prefix="i",
        initial={
            "doc_type": DocType.BOLETA,
            "customer_doc_type": customer.doc_type,
            "customer_doc": customer.doc,
            "customer_name": customer.name,
            "customer_address": customer.address,
            "customer_email": customer.email,
            "credit_days": folio.company.credit_days if folio.company else 0,
        },
    )
    others = Folio.objects.filter(property=request.property, status="open").exclude(pk=folio.pk)
    if folio.reservation_id:
        others = others.filter(Q(reservation=folio.reservation_id) | Q(kind__in=["company", "house"]))
    session = services.open_session_for(request.user, request.property)
    return render(
        request,
        "folio/folio_detail.html",
        {
            "folio": folio,
            "charges": folio.charges.select_related("concept", "invoice__series", "created_by"),
            "payments": folio.payments.select_related("created_by"),
            "invoices": folio.invoices.select_related("series"),
            "charge_form": charge_form,
            "payment_form": PaymentForm(
                prefix="p", initial={"amount": max(folio.balance, Decimal("0")) or None}
            ),
            "invoice_form": invoice_form,
            "others": others,
            "session": session,
            "uninvoiced_total": folio.uninvoiced_charges.aggregate(s=Sum("amount"))["s"] or 0,
            "deposits_available": billing.deposits_available(folio),
        },
    )


@require_POST
@require_perm("folio.view")
def folio_action(request, pk, action):
    folio = _get(request, pk)
    perms = request.user.pms_permissions(request.property)
    try:
        if action == "charge":
            if "folio.create" not in perms:
                raise PermissionDenied
            form = ChargeForm(request.POST, prefix="c")
            form.fields["concept"].queryset = Concept.objects.filter(property=request.property)
            if not form.is_valid():
                raise ValidationError(_("Revise los datos del cargo."))
            cd = form.cleaned_data
            discount = cd.get("discount_percent") or 0
            if discount:
                from apps.reservations.services import _check_discount

                _check_discount(request.user, request.property, discount)
            services.post_charge(
                folio,
                cd["concept"],
                cd["unit_price"],
                quantity=cd["quantity"],
                description=cd["description"],
                discount_percent=discount,
                user=request.user,
            )
            messages.success(request, _("Cargo registrado."))
        elif action == "pay":
            if "folio.create" not in perms:
                raise PermissionDenied
            form = PaymentForm(request.POST, prefix="p")
            if not form.is_valid():
                raise ValidationError(_("Revise los datos del pago."))
            cd = form.cleaned_data
            services.add_payment(
                folio,
                cd["method"],
                cd["amount"],
                user=request.user,
                reference=cd["reference"],
                is_deposit=cd["is_deposit"],
                refund=cd["refund"],
            )
            messages.success(request, _("Pago registrado."))
        elif action == "void_charge":
            charge = get_object_or_404(Charge, pk=request.POST.get("charge"), folio=folio)
            services.void_charge(charge, request.POST.get("reason", ""), request.user)
            messages.success(request, _("Cargo anulado."))
        elif action == "void_payment":
            payment = get_object_or_404(Payment, pk=request.POST.get("payment"), folio=folio)
            services.void_payment(payment, request.POST.get("reason", ""), request.user)
            messages.success(request, _("Pago anulado."))
        elif action == "transfer":
            target = get_object_or_404(Folio, pk=request.POST.get("target"), property=request.property)
            for cid in request.POST.getlist("charges"):
                services.transfer_charge(get_object_or_404(Charge, pk=cid, folio=folio), target, request.user)
            messages.success(request, _("Cargos transferidos al folio %(n)s.") % {"n": target.number})
        elif action == "split":
            new = services.create_folio(
                request.property,
                reservation=folio.reservation,
                guest=folio.guest,
                name=request.POST.get("name") or _("Cuenta separada"),
            )
            messages.success(request, _("Folio %(n)s creado.") % {"n": new.number})
            return redirect("folio:folio_detail", pk=new.pk)
        elif action == "invoice":
            form = InvoiceForm(request.POST, prefix="i")
            if not form.is_valid():
                raise ValidationError([f"{k}: {v[0]}" for k, v in form.errors.items()])
            cd = form.cleaned_data
            company = folio.company or (folio.reservation.company if folio.reservation else None)
            customer = billing.Customer(
                cd["customer_doc_type"],
                cd["customer_doc"].strip(),
                cd["customer_name"],
                cd["customer_address"],
                cd["customer_email"],
                company if cd["doc_type"] == DocType.FACTURA else None,
            )
            selected = request.POST.getlist("invoice_charges")
            charges = list(folio.charges.filter(pk__in=selected)) if selected else None
            inv = billing.issue_invoice(
                folio,
                cd["doc_type"],
                customer,
                user=request.user,
                charges=charges,
                currency=cd["currency"],
                due_days=cd.get("credit_days") or 0,
            )
            messages.success(request, _("Comprobante %(n)s emitido (simulación).") % {"n": inv.full_number})
            return redirect("billing:invoice_detail", pk=inv.pk)
        elif action == "close":
            services.close_folio(folio, request.user)
            messages.success(request, _("Folio cerrado."))
    except (ValidationError, PermissionDenied) as exc:
        _errors(request, exc)
    return redirect("folio:folio_detail", pk=folio.pk)


@require_perm("folio.view")
def folio_list(request):
    from .queries import with_folio_balance

    qs = with_folio_balance(
        Folio.objects.filter(property=request.property).select_related("reservation", "guest", "company")
    )
    status = request.GET.get("status", "open")
    if status != "all":
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(name__icontains=q) | Q(reservation__code__icontains=q))
    return render(request, "folio/folio_list.html", {"folios": qs[:200], "status": status, "q": q})


class HouseFolioForm(PropertyModelForm):
    class Meta:
        model = Folio
        fields = ["kind", "name", "company"]


@require_perm("folio.create")
def folio_create(request):
    form = HouseFolioForm(request.POST or None, property=request.property)
    form.fields["kind"].choices = [c for c in Folio.Kind.choices if c[0] in ("company", "house")]
    if request.method == "POST" and form.is_valid():
        folio = services.create_folio(
            request.property,
            kind=form.cleaned_data["kind"],
            name=form.cleaned_data["name"],
            company=form.cleaned_data["company"],
        )
        return redirect("folio:folio_detail", pk=folio.pk)
    return render(
        request, "core/simple_form.html", {"form": form, "title": _("Nuevo folio"), "back": "/folios/"}
    )


# --------------------------------------------------------------------------
# Caja (RF-CAJ-01 a RF-CAJ-04)
# --------------------------------------------------------------------------


@require_perm("folio.view")
def cash(request):
    prop = request.property
    session = services.open_session_for(request.user, prop)
    if request.method == "POST":
        try:
            if request.POST.get("action") == "open":
                register = get_object_or_404(CashRegister, pk=request.POST.get("register"), property=prop)
                services.open_cash_session(
                    register,
                    request.user,
                    _dec(request.POST.get("opening_pen")),
                    _dec(request.POST.get("opening_usd")),
                )
                messages.success(request, _("Caja abierta."))
            elif request.POST.get("action") == "expense" and session:
                services.add_petty_expense(
                    session,
                    request.POST.get("description", ""),
                    _dec(request.POST.get("amount")),
                    request.POST.get("receipt", ""),
                )
                messages.success(request, _("Gasto registrado."))
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
        return redirect("folio:cash")
    expected = services.expected_by_method(session) if session else {}
    sessions = CashSession.objects.filter(property=prop).select_related("user", "register")[:30]
    return render(
        request,
        "folio/cash.html",
        {
            "session": session,
            "expected": expected,
            "methods": Payment.Method.choices,
            "registers": CashRegister.objects.filter(property=prop, is_active=True),
            "sessions": sessions,
        },
    )


@require_perm("folio.view")
def cash_close(request, pk):
    session = get_object_or_404(CashSession, pk=pk, property=request.property)
    expected = services.expected_by_method(session)
    if request.method == "POST":
        counted = {m: request.POST.get(m, "0") or "0" for m, _label in Payment.Method.choices}
        try:
            services.close_cash_session(session, counted, request.user, request.POST.get("notes", ""))
            messages.success(request, _("Turno cerrado. Diferencia: S/ %(d)s") % {"d": session.difference})
            return redirect("folio:cash_session", pk=session.pk)
        except (ValidationError, PermissionDenied) as exc:
            _errors(request, exc)
    labels = dict(Payment.Method.choices)
    rows = [{"method": m, "label": labels[m], "expected": v} for m, v in expected.items() if m != "ledger"]
    return render(request, "folio/cash_close.html", {"session": session, "rows": rows})


@require_perm("folio.view")
def cash_session(request, pk):
    session = get_object_or_404(
        CashSession.objects.select_related("user", "register"), pk=pk, property=request.property
    )
    labels = dict(Payment.Method.choices)
    rows = []
    for m, label in labels.items():
        exp = Decimal(session.expected.get(m, "0")) if session.expected else None
        cnt = Decimal(session.counted.get(m, "0")) if session.counted else None
        rows.append(
            {
                "label": label,
                "expected": exp,
                "counted": cnt,
                "diff": (cnt - exp) if exp is not None and cnt is not None else None,
            }
        )
    return render(
        request,
        "folio/cash_session.html",
        {
            "session": session,
            "rows": rows,
            "payments": session.payments.select_related("folio").order_by("created_at"),
            "expenses": session.expenses.all(),
        },
    )


# --------------------------------------------------------------------------
# Cuentas por cobrar (RF-CAJ-05)
# --------------------------------------------------------------------------


@require_perm("folio.view")
def receivables(request):
    prop = request.property
    today = prop.current_business_date()
    if request.method == "POST":
        if not request.user.has_pms_perm(prop, "folio.edit"):
            raise PermissionDenied
        inv = get_object_or_404(Invoice, pk=request.POST.get("invoice"), property=prop)
        inv.is_paid = True
        inv.paid_at = today
        inv.save(update_fields=["is_paid", "paid_at"])
        from apps.core import audit
        from apps.core.models import AuditLog

        audit.log(
            AuditLog.Action.UPDATE,
            inv,
            changes={"pagado": [False, True]},
            reason=request.POST.get("reference", ""),
        )
        messages.success(request, _("Cobro registrado."))
        return redirect("folio:receivables")
    open_invoices = (
        Invoice.objects.filter(property=prop, is_paid=False, doc_type__in=["01", "03"])
        .exclude(status="voided")
        .select_related("company", "series")
    )
    buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "+90": Decimal("0")}
    rows = []
    for inv in open_invoices:
        days = (today - (inv.due_date or inv.issue_date)).days
        key = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "+90"
        buckets[key] += inv.total
        rows.append({"inv": inv, "days": max(0, days), "bucket": key})
    by_company = {}
    for row in rows:
        name = str(row["inv"].company or row["inv"].customer_name)
        by_company[name] = by_company.get(name, Decimal("0")) + row["inv"].total
    ledger_folios = Folio.objects.filter(property=prop, payments__method="ledger").distinct()
    return render(
        request,
        "folio/receivables.html",
        {
            "rows": rows,
            "buckets": buckets,
            "by_company": sorted(by_company.items(), key=lambda x: -x[1]),
            "ledger_folios": ledger_folios,
            "today": today,
            "soon": today + timedelta(days=7),
        },
    )
