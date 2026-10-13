"""Vista consolidada multi-propiedad: RF-MUL-02."""

from datetime import timedelta

from django.urls import reverse

from apps.accounts.models import PropertyAccess
from apps.reports import services as rep
from conftest import BUSINESS_DATE


def test_consolidated_compares_properties_rf_mul_02(setup, book, other_hotel, roles, login):
    book()
    end = BUSINESS_DATE + timedelta(days=2)
    rows, group = rep.consolidated([setup.hotel, other_hotel], BUSINESS_DATE, end)
    assert [r["property"] for r in rows] == [setup.hotel, other_hotel]
    assert rows[0]["sold"] == 2 and rows[1]["sold"] == 0
    assert group["sold"] == 2 and group["available"] == rows[0]["available"] + rows[1]["available"]
    PropertyAccess.objects.create(user=setup.manager, property=other_hotel, role=roles["manager"])
    resp = login(setup.manager).get(reverse("reports:consolidated"))
    assert resp.status_code == 200 and len(resp.context["rows"]) == 2
