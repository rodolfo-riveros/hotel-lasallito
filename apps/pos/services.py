"""Comandas, cocina y liquidación de cuentas (RF-POS-02, RF-POS-04, RF-POS-08)."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditLog, Sequence
from apps.folio import services as folio_services
from apps.folio.models import Folio
from apps.reservations.models import Reservation

from .models import MenuItem, Order, OrderItem


def open_order(outlet, *, user, table=None, covers=1, reservation=None) -> Order:
    if table is not None and Order.objects.filter(table=table, status=Order.Status.OPEN).exists():
        raise ValidationError(_("La mesa ya tiene una cuenta abierta."))
    number = f"C{Sequence.next_value(outlet.property, 'pos_order'):06d}"
    return Order.objects.create(
        property=outlet.property,
        number=number,
        outlet=outlet,
        table=table,
        waiter=user,
        covers=covers,
        reservation=reservation,
    )


def add_item(order: Order, menu_item: MenuItem, quantity=1, notes="") -> OrderItem:
    if order.status != Order.Status.OPEN:
        raise ValidationError(_("La cuenta está cerrada."))
    if not menu_item.is_available:
        raise ValidationError(_("%(i)s no está disponible.") % {"i": menu_item.name})
    return OrderItem.objects.create(
        order=order,
        menu_item=menu_item,
        quantity=quantity,
        unit_price=menu_item.price,
        notes=notes,
        station=menu_item.station,
    )


def send_to_kitchen(order: Order) -> int:
    """RF-POS-02/08: envía a cocina o barra lo pendiente."""
    now = timezone.now()
    items = order.items.filter(status=OrderItem.Status.PENDING)
    for item in items:
        item.status = OrderItem.Status.SERVED if item.station == "none" else OrderItem.Status.SENT
        item.sent_at = now
        item.save(update_fields=["status", "sent_at"])
    return items.count()


def advance_item(item: OrderItem) -> OrderItem:
    """KDS: enviado → preparando → listo → servido."""
    flow = {
        OrderItem.Status.SENT: OrderItem.Status.PREPARING,
        OrderItem.Status.PREPARING: OrderItem.Status.READY,
        OrderItem.Status.READY: OrderItem.Status.SERVED,
    }
    if item.status in flow:
        item.status = flow[item.status]
        if item.status == OrderItem.Status.READY:
            item.ready_at = timezone.now()
        item.save(update_fields=["status", "ready_at"])
    return item


@transaction.atomic
def void_item(item: OrderItem, reason: str, user) -> OrderItem:
    if item.status not in (OrderItem.Status.PENDING,) and not user.has_pms_perm(
        item.order.property, "pos.void"
    ):
        raise PermissionDenied(_("Solo un supervisor anula platos ya enviados."))
    item.status = OrderItem.Status.VOID
    item.void_reason = reason
    item.save()
    audit.log(AuditLog.Action.VOID, item.order, changes={"item": str(item)}, reason=reason, user=user)
    return item


@transaction.atomic
def split_order(order: Order, item_ids: list[int], user) -> Order:
    """RF-POS-02: divide la cuenta moviendo platos a una cuenta nueva."""
    if order.status != Order.Status.OPEN:
        raise ValidationError(_("La cuenta está cerrada."))
    child = open_order(order.outlet, user=user, covers=1, reservation=order.reservation)
    child.parent = order
    child.table = None
    child.save()
    moved = order.items.filter(pk__in=item_ids).exclude(status=OrderItem.Status.VOID).update(order=child)
    if not moved:
        raise ValidationError(_("Seleccione los platos a separar."))
    return child


def _post_items(order: Order, folio: Folio):
    concept = order.outlet.concept or folio_services.get_concept(order.property, "fnb")
    for item in order.items.exclude(status=OrderItem.Status.VOID).select_related("menu_item"):
        folio_services.post_charge(
            folio,
            concept,
            item.unit_price,
            quantity=item.quantity,
            description=f"{order.outlet.name}: {item.menu_item.name}",
            source="pos",
            reference=order.number,
        )
    if order.tip:
        folio_services.post_charge(
            folio,
            folio_services.get_concept(order.property, "tip"),
            order.tip,
            description=_("Propina %(n)s") % {"n": order.number},
            source="pos",
            reference=order.number,
        )


@transaction.atomic
def charge_to_room(order: Order, reservation: Reservation, *, user, signature="") -> Order:
    """RF-POS-04: cargo a habitación con firma digital."""
    if order.status != Order.Status.OPEN:
        raise ValidationError(_("La cuenta ya está cerrada."))
    if reservation.status != Reservation.Status.CHECKED_IN:
        raise ValidationError(_("El huésped no está en casa."))
    if not signature:
        raise ValidationError(_("Se requiere la firma del huésped."))
    if order.total <= 0:
        raise ValidationError(_("La cuenta está vacía."))
    folio = folio_services.main_folio(reservation)
    _post_items(order, folio)
    order.reservation = reservation
    order.folio = folio
    order.signature = signature
    order.settlement = Order.Settlement.ROOM
    order.status = Order.Status.CLOSED
    order.closed_at = timezone.now()
    order.save()
    _close_table_items(order)
    return order


@transaction.atomic
def pay_order(
    order: Order, payments: list[tuple[str, Decimal]], *, user, tip=Decimal("0"), doc_type="03", customer=None
) -> tuple[Order, object]:
    """Cobro directo con uno o varios medios y emisión del comprobante."""
    from apps.billing import services as billing

    if order.status != Order.Status.OPEN:
        raise ValidationError(_("La cuenta ya está cerrada."))
    order.tip = folio_services.q2(tip)
    order.save(update_fields=["tip"])
    folio = folio_services.create_folio(
        order.property,
        kind=Folio.Kind.POS,
        name=f"{order.outlet.name} {order.number}",
        guest=order.reservation.guest if order.reservation else None,
    )
    _post_items(order, folio)
    total = folio.total_charges
    paid = sum((Decimal(a) for _m, a in payments), Decimal("0"))
    if folio_services.q2(paid) != folio_services.q2(total):
        raise ValidationError(
            _("Los pagos (%(p)s) no cuadran con el total (%(t)s).") % {"p": paid, "t": total}
        )
    for method, amount in payments:
        folio_services.add_payment(folio, method, amount, user=user)
    customer = customer or billing.Customer("0", "", _("Clientes varios"))
    invoice = billing.issue_invoice(folio, doc_type, customer, user=user)
    folio_services.close_folio(folio, user)
    order.folio = folio
    order.settlement = Order.Settlement.PAID
    order.status = Order.Status.CLOSED
    order.closed_at = timezone.now()
    order.save()
    _close_table_items(order)
    return order, invoice


def _close_table_items(order: Order):
    order.items.filter(status__in=[OrderItem.Status.PENDING]).update(status=OrderItem.Status.SERVED)


def breakfast_list(property_obj, day):
    """RF-POS-06: huéspedes en casa con desayuno incluido para el día."""
    return (
        Reservation.objects.filter(
            property=property_obj,
            status__in=[Reservation.Status.CHECKED_IN],
            arrival__lt=day,
            departure__gte=day,
        )
        .exclude(rate_plan__meal_plan="RO")
        .select_related("room", "guest", "rate_plan")
        .order_by("room__number")
    )
