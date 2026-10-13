"""Venta de tours y traslados, agenda de recojos y liquidación (RF-TUR-02 a 05)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.folio import services as folio_services

from .models import Operator, Service, ServiceBooking


@transaction.atomic
def book_service(
    service: Service,
    *,
    date,
    pax=1,
    reservation=None,
    guest_name="",
    pickup_time=None,
    pickup_point="",
    notes="",
    user=None,
    charge_folio=True,
) -> ServiceBooking:
    """RF-TUR-02: vende el servicio y lo carga al folio del huésped."""
    if pax < 1:
        raise ValidationError(_("Indique los pasajeros."))
    sb = ServiceBooking.objects.create(
        property=service.property,
        service=service,
        reservation=reservation,
        guest_name=guest_name or (reservation.guest.full_name if reservation else ""),
        date=date,
        pickup_time=pickup_time or service.pickup_time,
        pickup_point=pickup_point or "Lobby del hotel",
        pax=pax,
        unit_price=service.price,
        unit_cost=service.cost,
        notes=notes,
    )
    if reservation is not None and charge_folio:
        concept = folio_services.get_concept(service.property, "transfer" if service.is_transfer else "tour")
        sb.charge = folio_services.post_charge(
            folio_services.main_folio(reservation),
            concept,
            service.price,
            quantity=pax,
            description=f"{service.name} {date:%d/%m}",
            service_date=date,
            source="tour",
            reference=f"TUR{sb.pk}",
        )
        sb.save(update_fields=["charge"])
    return sb


@transaction.atomic
def cancel_service(sb: ServiceBooking, user, reason="") -> ServiceBooking:
    if sb.charge_id and not sb.charge.is_void:
        folio_services.void_charge(sb.charge, reason or _("Tour anulado"), user)
    sb.status = ServiceBooking.Status.CANCELLED
    sb.save(update_fields=["status"])
    return sb


def agenda(property_obj, day):
    """RF-TUR-03: recojos del día ordenados por hora."""
    return (
        ServiceBooking.objects.filter(property=property_obj, date=day)
        .exclude(status=ServiceBooking.Status.CANCELLED)
        .select_related("service__operator", "reservation__room")
        .order_by("pickup_time", "service__name")
    )


def send_agenda(property_obj, day, operator: Operator) -> int:
    """Envía al operador la lista de pasajeros y recojos del día."""
    from apps.comms.services import send_message

    rows = [b for b in agenda(property_obj, day) if b.service.operator_id == operator.pk]
    if not rows or not operator.email:
        return 0
    lines = [
        f"{b.pickup_time:%H:%M} · {b.service.name} · {b.guest_name} · {b.pax} pax · {b.pickup_point}"
        + (f" · hab. {b.reservation.room.number}" if b.reservation and b.reservation.room else "")
        + (f" · {b.notes}" if b.notes else "")
        for b in rows
    ]
    send_message(
        property_obj,
        "email",
        operator.email,
        f"Agenda {day:%d/%m/%Y} · {property_obj.name}",
        "\n".join(lines),
    )
    ServiceBooking.objects.filter(pk__in=[b.pk for b in rows]).update(
        sent_to_operator_at=timezone.now(), status=ServiceBooking.Status.CONFIRMED
    )
    return len(rows)


def settlement(property_obj, start, end):
    """RF-TUR-05: ventas, costo, margen y liquidación por operador."""
    rows = (
        ServiceBooking.objects.filter(property=property_obj, date__gte=start, date__lt=end)
        .exclude(status=ServiceBooking.Status.CANCELLED)
        .values("service__operator__name")
        .annotate(
            n=Count("pk"),
            n_pax=Sum("pax"),
            sales=Sum(F("unit_price") * F("pax")),
            cost=Sum(F("unit_cost") * F("pax")),
        )
        .order_by("service__operator__name")
    )
    result = []
    for r in rows:
        sales, cost = r["sales"] or Decimal("0"), r["cost"] or Decimal("0")
        result.append(
            {
                **r,
                "operator": r["service__operator__name"] or _("Sin operador"),
                "margin": sales - cost,
                "margin_percent": ((sales - cost) * 100 / sales).quantize(Decimal("0.1")) if sales else 0,
            }
        )
    return result


def train_alerts(property_obj, day):
    """RF-TUR-04: huéspedes con tren al día siguiente (desayuno temprano, box lunch y equipaje)."""
    from datetime import timedelta

    from apps.reservations.models import Reservation

    return Reservation.objects.filter(
        property=property_obj, status="checked_in", train_date=day + timedelta(days=1)
    ).select_related("guest", "room")
