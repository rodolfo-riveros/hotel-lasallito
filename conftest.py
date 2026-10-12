from datetime import time

import pytest

from apps.accounts.models import PropertyAccess, Role, User
from apps.accounts.services import seed_default_roles
from apps.core.models import Property

TEST_PASSWORD = "clave-de-prueba-123"


@pytest.fixture
def roles(db):
    return {r.code: r for r in seed_default_roles()}


@pytest.fixture
def hotel(db):
    return Property.objects.create(
        code="hotel-prueba",
        name="Hotel de Prueba",
        legal_name="Hotel de Prueba S.A.C.",
        ruc="20600000001",
        check_in_time=time(14),
        check_out_time=time(11),
    )


@pytest.fixture
def other_hotel(db):
    return Property.objects.create(
        code="otro-hotel", name="Otro Hotel", legal_name="Otro Hotel S.A.C.", ruc="20600000002"
    )


@pytest.fixture
def make_user(db, hotel, roles):
    """Crea un usuario con el rol indicado en `hotel` (o sin acceso si role=None)."""

    def _make(username="usuario", role="receptionist", property_obj=None, **extra):
        user = User.objects.create_user(username=username, password=TEST_PASSWORD, **extra)
        if role:
            PropertyAccess.objects.create(user=user, property=property_obj or hotel, role=roles[role])
        return user

    return _make


@pytest.fixture
def login(client):
    def _login(user):
        client.force_login(user)
        return client

    return _login


@pytest.fixture
def admin_user(make_user):
    return make_user("admin", role="admin")


@pytest.fixture
def receptionist(make_user):
    return make_user("recepcion", role="receptionist")


__all__ = ["Role", "TEST_PASSWORD"]


# --------------------------------------------------------------------------
# Hotel de prueba con habitaciones, tarifas e impuestos (fase 1)
# --------------------------------------------------------------------------

BUSINESS_DATE = __import__("datetime").date(2026, 7, 10)


@pytest.fixture
def setup(db, hotel, roles, make_user):
    """Hotel con 2 tipos (3 dobles, 1 suite), tarifa rack con temporada alta, IGV 18% y tipo de cambio."""
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace

    from apps.core.models import ExchangeRate, TaxRule
    from apps.folio.models import CashRegister
    from apps.guests.models import Guest
    from apps.rates.models import CancellationPolicy, RatePlan, RatePrice, Season
    from apps.rooms.models import Room, RoomType

    hotel.business_date = BUSINESS_DATE
    hotel.save()
    TaxRule.objects.create(
        property=hotel, code="igv", name="IGV", rate=Decimal("18"), exempt_for_non_domiciled=True
    )
    ExchangeRate.objects.create(date=date(2026, 7, 1), currency_id="USD", buy="3.70", sell="3.75")
    double = RoomType.objects.create(
        property=hotel,
        code="dbl",
        name="Doble",
        base_occupancy=2,
        max_adults=3,
        max_children=1,
        max_occupancy=3,
    )
    suite = RoomType.objects.create(
        property=hotel,
        code="ste",
        name="Suite",
        base_occupancy=2,
        max_adults=2,
        max_children=2,
        max_occupancy=4,
    )
    rooms = [
        Room.objects.create(property=hotel, number="101", room_type=double, floor=1),
        Room.objects.create(property=hotel, number="102", room_type=double, floor=1, view="mountain"),
        Room.objects.create(property=hotel, number="201", room_type=double, floor=2, is_quiet=True),
        Room.objects.create(property=hotel, number="301", room_type=suite, floor=3),
    ]
    flexible = CancellationPolicy.objects.create(
        property=hotel,
        name="Flexible",
        free_until_days=2,
        penalty="first_night",
        no_show_penalty="first_night",
    )
    nonref = CancellationPolicy.objects.create(property=hotel, name="No reembolsable", is_non_refundable=True)
    rack = RatePlan.objects.create(property=hotel, code="rack", name="Rack", cancellation_policy=flexible)
    high = Season.objects.create(
        property=hotel,
        name="Alta",
        kind="high",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 31),
        priority=2,
    )
    RatePrice.objects.create(
        property=hotel,
        rate_plan=rack,
        room_type=double,
        price=Decimal("300"),
        extra_adult=Decimal("80"),
        child=Decimal("40"),
    )
    RatePrice.objects.create(
        property=hotel,
        rate_plan=rack,
        room_type=double,
        season=high,
        price=Decimal("400"),
        extra_adult=Decimal("80"),
    )
    RatePrice.objects.create(property=hotel, rate_plan=rack, room_type=suite, price=Decimal("600"))
    corporate = RatePlan.objects.create(
        property=hotel,
        code="corp",
        name="Corporativa",
        kind="corporate",
        base_plan=rack,
        adjustment_percent=Decimal("-10"),
        cancellation_policy=flexible,
    )
    nonref_plan = RatePlan.objects.create(
        property=hotel,
        code="nr",
        name="No reembolsable",
        base_plan=rack,
        adjustment_percent=Decimal("-15"),
        cancellation_policy=nonref,
    )
    peruvian = Guest.objects.create(
        first_name="María",
        last_name="Quispe",
        doc_type="1",
        doc_number="45678912",
        nationality="PE",
        email="maria@example.com",
        language="es",
    )
    foreigner = Guest.objects.create(
        first_name="John",
        last_name="Smith",
        doc_type="7",
        doc_number="X1234567",
        nationality="US",
        residence_country="US",
        email="john@example.com",
        language="en",
        peru_entry_date=date(2026, 7, 5),
    )
    register = CashRegister.objects.create(property=hotel, name="Recepción")
    return SimpleNamespace(
        hotel=hotel,
        double=double,
        suite=suite,
        rooms=rooms,
        rack=rack,
        corporate=corporate,
        nonref=nonref_plan,
        high=high,
        flexible=flexible,
        peruvian=peruvian,
        foreigner=foreigner,
        register=register,
        receptionist=make_user("lucia", role="receptionist"),
        manager=make_user("gerente", role="manager"),
        auditor=make_user("nocturno", role="night_auditor"),
        admin=make_user("admin", role="admin"),
    )


@pytest.fixture
def book(setup):
    """Crea reservas rápidamente: book(arrival_offset=0, nights=2, room=None, ...)."""
    from datetime import timedelta

    from apps.reservations.services import ReservationData, create_reservation

    def _book(
        arrival_offset=0,
        nights=2,
        room=None,
        room_type=None,
        guest=None,
        plan=None,
        user=None,
        allow_overbooking=False,
        **extra,
    ):
        arrival = BUSINESS_DATE + timedelta(days=arrival_offset)
        data = ReservationData(
            guest=guest or setup.peruvian,
            room_type=room_type or (room.room_type if room else setup.double),
            rate_plan=plan or setup.rack,
            arrival=arrival,
            departure=arrival + timedelta(days=nights),
            room=room,
            **extra,
        )
        return create_reservation(
            setup.hotel, data, user=user or setup.receptionist, allow_overbooking=allow_overbooking
        )

    return _book
