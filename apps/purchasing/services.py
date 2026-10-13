"""Flujo de compras: requisición → aprobación por monto → cotizaciones → OC → recepción (RF-COM-01 a 05)."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.billing.validators import ruc_is_valid
from apps.core import audit
from apps.core.models import AuditLog, Sequence
from apps.inventory import services as inv

from .models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    Quotation,
    Requisition,
    SupplierInvoice,
)


def validate_supplier_ruc(ruc: str):
    if not ruc_is_valid(ruc):
        raise ValidationError(_("RUC del proveedor inválido."))


def can_approve(user, property_obj, amount: Decimal) -> bool:
    """Aprobación por monto: el rol necesita permiso de aprobar y un límite suficiente (0 = sin límite)."""
    if user.is_superuser:
        return True
    if not user.has_pms_perm(property_obj, "purchasing.approve"):
        return False
    role = user.role_for(property_obj)
    return role is not None and (role.approval_limit == 0 or amount <= role.approval_limit)


@transaction.atomic
def submit(req: Requisition, user) -> Requisition:
    if req.status != Requisition.Status.DRAFT:
        raise ValidationError(_("La requisición ya fue enviada."))
    if not req.lines.exists():
        raise ValidationError(_("Agregue artículos."))
    req.status = Requisition.Status.SUBMITTED
    req.save(update_fields=["status"])
    from apps.comms.services import notify_role

    notify_role(
        req.property,
        "manager",
        _("Requisición %(n)s por aprobar") % {"n": req.number},
        _("Monto estimado S/ %(m)s") % {"m": req.estimated_total},
        url=f"/compras/requisiciones/{req.pk}/",
    )
    return req


@transaction.atomic
def decide(req: Requisition, user, approve: bool, reason="") -> Requisition:
    if req.status != Requisition.Status.SUBMITTED:
        raise ValidationError(_("La requisición no está por aprobar."))
    if approve and not can_approve(user, req.property, req.estimated_total):
        raise PermissionDenied(_("El monto supera su límite de aprobación."))
    if not approve and not user.has_pms_perm(req.property, "purchasing.approve"):
        raise PermissionDenied
    req.status = Requisition.Status.APPROVED if approve else Requisition.Status.REJECTED
    req.approved_by = user
    req.approved_at = timezone.now()
    req.save()
    audit.log(
        AuditLog.Action.APPROVE if approve else AuditLog.Action.VOID,
        req,
        changes={"monto": str(req.estimated_total)},
        reason=reason,
        user=user,
    )
    return req


@transaction.atomic
def order_from_quotation(quotation: Quotation, user) -> PurchaseOrder:
    req = quotation.requisition
    if req.status != Requisition.Status.APPROVED:
        raise ValidationError(_("La requisición debe estar aprobada."))
    Quotation.objects.filter(requisition=req).update(selected=False)
    quotation.selected = True
    quotation.save(update_fields=["selected"])
    today = req.property.current_business_date()
    po = PurchaseOrder.objects.create(
        property=req.property,
        number=f"OC{Sequence.next_value(req.property, 'po'):05d}",
        supplier=quotation.supplier,
        requisition=req,
        warehouse=req.warehouse,
        order_date=today,
        expected_date=today + timedelta(days=quotation.delivery_days),
        status=PurchaseOrder.Status.SENT,
    )
    for ln in quotation.lines.all():
        PurchaseOrderLine.objects.create(
            order=po, item=ln.item, quantity=ln.quantity, unit_price=ln.unit_price
        )
    req.status = Requisition.Status.ORDERED
    req.save(update_fields=["status"])
    audit.log(AuditLog.Action.CREATE, po, changes={"total": str(po.total)}, user=user)
    return po


@transaction.atomic
def receive_goods(
    po: PurchaseOrder, quantities: dict, *, user, guide="", invoice="", lots: dict | None = None
):
    """RF-COM-03: recepción parcial o total contra la OC; ingresa al almacén al costo de la OC."""
    if po.status in (PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.CANCELLED):
        raise ValidationError(_("La orden ya está cerrada."))
    lots = lots or {}
    receipt = GoodsReceipt.objects.create(
        property=po.property,
        order=po,
        date=po.property.current_business_date(),
        guide_number=guide,
        invoice_number=invoice,
    )
    received_any = False
    for line in po.lines.select_related("item").select_for_update():
        qty = Decimal(str(quantities.get(line.pk) or 0))
        if qty <= 0:
            continue
        if qty > line.pending:
            raise ValidationError(_("Se recibe más de lo pedido en %(i)s.") % {"i": line.item.name})
        lot_code, expiry = lots.get(line.pk, ("", None))
        base_qty = qty * line.item.purchase_factor
        unit_cost = line.unit_price / line.item.purchase_factor
        inv.receive(
            po.warehouse,
            line.item,
            base_qty,
            unit_cost,
            reference=po.number,
            notes=_("Guía %(g)s · factura %(f)s") % {"g": guide or "-", "f": invoice or "-"},
            lot_code=lot_code,
            expiry=expiry,
        )
        line.received_qty += qty
        line.save(update_fields=["received_qty"])
        received_any = True
    if not received_any:
        raise ValidationError(_("Indique las cantidades recibidas."))
    po.status = (
        PurchaseOrder.Status.RECEIVED
        if all(ln.pending <= 0 for ln in po.lines.all())
        else PurchaseOrder.Status.PARTIAL
    )
    po.save(update_fields=["status"])
    return receipt


def register_invoice(po: PurchaseOrder, number, amount, issue_date=None) -> SupplierInvoice:
    issue_date = issue_date or po.property.current_business_date()
    return SupplierInvoice.objects.create(
        property=po.property,
        supplier=po.supplier,
        order=po,
        number=number,
        issue_date=issue_date,
        due_date=issue_date + timedelta(days=po.supplier.payment_days),
        amount=Decimal(amount),
    )
