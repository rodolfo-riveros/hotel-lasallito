"""Modo aula: RF-SIM-01 a RF-SIM-05."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.billing.models import SimulationSettings
from apps.classroom import services
from apps.classroom.models import PracticeEvent, ScenarioRun
from apps.classroom.scenarios import progress
from apps.core.models import Property


@pytest.fixture
def teacher(setup, make_user):
    return make_user("docente", role="teacher")


def test_practice_property_is_isolated_and_teacher_sees_it_rf_sim_02(setup, teacher):
    from apps.accounts.models import PropertyAccess
    from apps.core.models import TaxRule

    prop = services.create_practice_property("Grupo A", "aula-a", template=setup.hotel, user=teacher)
    assert TaxRule.objects.filter(property=prop, code="igv").exists()
    assert PropertyAccess.objects.filter(user=teacher, property=prop, role__code="teacher").exists()
    assert not PropertyAccess.objects.filter(user=setup.receptionist, property=prop).exists()


def test_reset_archives_and_clones_rf_sim_01(setup, teacher):
    old_pk = setup.hotel.pk
    fresh = services.archive_and_clone(setup.hotel, teacher)
    old = Property.objects.get(pk=old_pk)
    assert not old.is_active and "-arch-" in old.code
    assert fresh.code == "hotel-prueba" and fresh.is_active
    assert setup.receptionist.property_accesses.filter(property=fresh, is_active=True).exists()


def test_load_sample_data_fills_a_new_hotel(setup, teacher):
    from apps.channels.models import Channel
    from apps.reservations.models import Reservation
    from apps.tours.models import Service

    prop = services.create_practice_property("Grupo B", "aula-b", template=setup.hotel, user=teacher)
    services.load_sample_data(prop, teacher)
    assert Reservation.objects.filter(property=prop).exists()
    assert Channel.objects.filter(property=prop).count() == 4
    assert Service.objects.filter(property=prop, kind="machu_picchu").exists()


def test_late_group_scenario_checks_steps_rf_sim_03(setup, teacher):
    from apps.frontdesk import services as fd

    run = services.start_scenario(setup.hotel, "late_group", teacher)
    assert len(run.data["reservations"]) == 3
    assert [done for _s, done in progress(run)] == [False, False, False]
    from apps.reservations.models import Reservation

    rooms = iter(setup.rooms)
    for r in Reservation.objects.filter(pk__in=run.data["reservations"]):
        fd.check_in(r, user=setup.receptionist, room=next(rooms), charge_early=False, allow_dirty=True)
    assert [done for _s, done in progress(run)] == [True, True, False]


def test_cash_difference_scenario_rf_sim_03(setup, teacher, book):
    from apps.folio import services as folio

    run = services.start_scenario(setup.hotel, "cash_difference", teacher)
    session = folio.open_cash_session(setup.register, setup.receptionist)
    folio.add_payment(book().main_folio, "cash_pen", Decimal("100"), user=setup.receptionist)
    folio.close_cash_session(session, {"cash_pen": "90"}, setup.receptionist, notes="Faltan S/ 10")
    steps = services.refresh_run(run)
    assert all(done for _s, done in steps)
    run.refresh_from_db()
    assert run.completed_at is not None


def test_teacher_events_rf_sim_04(setup, teacher, book):
    from apps.reservations.models import Reservation

    r = book(arrival_offset=5)
    services.fire(setup.hotel, "walk_ins", teacher)
    services.fire(setup.hotel, "agency_cancel", teacher)
    r.refresh_from_db()
    assert r.status == "cancelled"
    services.fire(setup.hotel, "sunat_down", teacher)
    assert SimulationSettings.objects.get(property=setup.hotel).connection_down
    services.fire(setup.hotel, "sunat_up", teacher)
    assert not SimulationSettings.objects.get(property=setup.hotel).connection_down
    assert PracticeEvent.objects.count() == 4
    assert Reservation.objects.filter(status="cancelled").count() == 1


def test_teacher_panel_progress_rf_sim_05(setup, teacher, login):
    services.start_scenario(setup.hotel, "credit_note", teacher)
    client = login(teacher)
    resp = client.get(reverse("classroom:panel"))
    assert resp.status_code == 200
    students = resp.context["students"][0]
    assert {m["user"].username for m in students["members"]} >= {"lucia", "gerente"}
    assert (
        client.get(reverse("classroom:student", args=[setup.hotel.pk, setup.receptionist.pk])).status_code
        == 200
    )
    assert login(setup.receptionist).get(reverse("classroom:guide")).status_code == 200
    assert login(setup.receptionist).get(reverse("classroom:panel")).status_code == 403
    assert ScenarioRun.objects.count() == 1
