"""Envío programado de reportes por correo: RF-REP-06."""

from datetime import date

from django.urls import reverse

from apps.comms.models import Message
from apps.reports.models import ReportSubscription
from apps.reports.schedule import period, send_due


def test_periods_by_frequency():
    monday, tuesday, first = date(2026, 7, 13), date(2026, 7, 14), date(2026, 8, 1)
    assert period("daily", tuesday) == (date(2026, 7, 13), tuesday)
    assert period("weekly", monday) == (date(2026, 7, 6), monday)
    assert period("weekly", tuesday) is None
    assert period("monthly", first) == (date(2026, 7, 1), first)
    assert period("monthly", tuesday) is None


def test_scheduled_report_is_emailed_once_per_day_rf_rep_06(setup, book, login):
    book(arrival_offset=-2)
    ReportSubscription.objects.create(
        property=setup.hotel,
        report="kpis",
        format="xlsx",
        recipients="gerente@hotel.example, dueno@hotel.example",
    )
    ReportSubscription.objects.create(
        property=setup.hotel, report="area", frequency="weekly", recipients="x@hotel.example"
    )
    today = date(2026, 7, 14)  # martes: el semanal no toca
    assert send_due(setup.hotel, today) == 2
    msg = Message.objects.get(to="gerente@hotel.example")
    assert "Indicadores" in msg.subject
    assert send_due(setup.hotel, today) == 0  # no se repite el mismo día
    assert login(setup.manager).get(reverse("reports:subscription_list")).status_code == 200
