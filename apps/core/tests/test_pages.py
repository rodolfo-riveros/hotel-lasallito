"""Todas las pantallas cargan con el hotel de práctica (RF-SIM-01) y respetan permisos (RNF-SEG-02)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo(hotel, roles, make_user):
    from apps.core.demo import load_bookings, load_operations, load_phase2

    admin = make_user("admin", role="admin")
    hotel.business_date = None
    hotel.save()
    _t, _r, guests = load_operations(hotel)
    load_bookings(hotel, admin, guests)
    load_phase2(hotel)
    return admin


PAGES = [
    "core:dashboard",
    "frontdesk:panel",
    "frontdesk:walk_in",
    "frontdesk:luggage",
    "frontdesk:shift_log",
    "frontdesk:wakeups",
    "frontdesk:night_audit",
    "reservations:reservation_list",
    "reservations:tape_chart",
    "reservations:reservation_create",
    "reservations:group_list",
    "reservations:group_create",
    "reservations:waitlist_list",
    "rooms:rack",
    "rooms:roomtype_list",
    "rooms:room_list",
    "rooms:room_create",
    "rooms:block_list",
    "rates:calendar",
    "rates:plan_list",
    "rates:price_list",
    "rates:season_list",
    "rates:policy_create",
    "guests:guest_list",
    "guests:guest_create",
    "guests:company_list",
    "folio:folio_list",
    "folio:cash",
    "folio:receivables",
    "folio:concept_list",
    "billing:invoice_list",
    "billing:simulator",
    "billing:ple",
    "billing:series_list",
    "housekeeping:board",
    "housekeeping:my_tasks",
    "housekeeping:linen",
    "housekeeping:minibar",
    "housekeeping:lost_list",
    "pos:outlets",
    "pos:kds",
    "pos:breakfast",
    "pos:menuitem_list",
    "pos:table_list",
    "reports:index",
    "comms:inbox",
    "comms:automations",
    "comms:notifications",
    "comms:template_list",
    "inventory:stock",
    "inventory:movement",
    "inventory:alerts",
    "inventory:counts",
    "inventory:waste_list",
    "inventory:recipes",
    "inventory:item_list",
    "inventory:valuation",
    "inventory:warehouse_list",
    "purchasing:requisition_list",
    "purchasing:requisition_create",
    "purchasing:po_list",
    "purchasing:payables",
    "purchasing:supplier_list",
    "maintenance:wo_list",
    "maintenance:wo_create",
    "maintenance:costs",
    "maintenance:asset_list",
    "maintenance:plan_list",
    "portal:staff_requests",
    "portal:staff_surveys",
    "portal:staff_complaints",
]


def test_all_pages_render_for_admin(demo, client):
    client.force_login(demo)
    for name in PAGES:
        response = client.get(reverse(name))
        assert response.status_code in (200, 302), f"{name}: {response.status_code}"


def test_detail_pages_render(demo, client):
    from apps.pos.models import Outlet
    from apps.reservations.models import Reservation

    client.force_login(demo)
    r = Reservation.objects.filter(status="checked_in").first()
    arriving = Reservation.objects.filter(status="confirmed").first()
    for url in [
        reverse("reservations:reservation_detail", args=[r.pk]),
        reverse("reservations:reservation_edit", args=[arriving.pk]),
        reverse("reservations:reservation_pdf", args=[r.pk]),
        reverse("frontdesk:check_in", args=[arriving.pk]),
        reverse("frontdesk:check_out", args=[r.pk]),
        reverse("frontdesk:move_room", args=[r.pk]),
        reverse("folio:folio_detail", args=[r.main_folio.pk]),
        reverse("guests:guest_detail", args=[r.guest.pk]) + "?ver=1",
        reverse("pos:floor", args=[Outlet.objects.first().pk]),
        reverse("pos:public_menu", args=[Outlet.objects.first().pk]) + "?lang=en",
    ]:
        assert client.get(url).status_code == 200, url
    for key in [
        "kpis",
        "area",
        "channel",
        "country",
        "in_house",
        "arrivals",
        "rooms",
        "forecast",
        "mincetur",
        "pricing",
    ]:
        assert client.get(reverse("reports:report", args=[key])).status_code == 200, key
    assert client.get(reverse("reports:report", args=["kpis"]) + "?format=xlsx").status_code == 200
    assert client.get(reverse("frontdesk:contingency", args=["en-casa", "pdf"])).status_code == 200


def test_quote_preview_htmx(demo, client):
    from apps.rates.models import RatePlan
    from apps.rooms.models import RoomType

    client.force_login(demo)
    rt = RoomType.objects.get(code="mat")
    plan = RatePlan.objects.get(code="rack-bb")
    from datetime import timedelta

    day = demo.property_accesses.first().property.current_business_date() + timedelta(days=20)
    response = client.get(
        reverse("reservations:quote_preview"),
        {
            "arrival": day,
            "departure": day + timedelta(days=2),
            "room_type": rt.pk,
            "rate_plan": plan.pk,
            "adults": 2,
            "children": 0,
            "extra_beds": 0,
            "cribs": 0,
            "status": "confirmed",
            "channel": "direct",
            "guarantee": "none",
        },
    )
    assert response.status_code == 200
    assert b"habitaci" in response.content


def test_housekeeper_sees_only_her_area(demo, client, make_user):
    maid = make_user("ana", role="housekeeping")
    client.force_login(maid)
    assert client.get(reverse("housekeeping:my_tasks")).status_code == 200
    assert client.get(reverse("folio:folio_list")).status_code == 403
    assert client.get(reverse("billing:invoice_list")).status_code == 403
