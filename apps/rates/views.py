from datetime import timedelta

from django import forms
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.decorators import require_perm
from apps.core.crud import Crud, PropertyModelForm
from apps.rooms.models import RoomType

from .models import CancellationPolicy, DateRestriction, Promotion, RatePlan, RatePrice, Season
from .services import quote


def _date_widgets(*names):
    return {n: forms.DateInput(attrs={"type": "date"}) for n in names}


class RatePlanForm(PropertyModelForm):
    class Meta:
        model = RatePlan
        exclude = ["property", "created_by", "updated_by"]


class SeasonForm(PropertyModelForm):
    class Meta:
        model = Season
        exclude = ["property", "created_by", "updated_by"]
        widgets = _date_widgets("start_date", "end_date")


class RestrictionForm(PropertyModelForm):
    class Meta:
        model = DateRestriction
        exclude = ["property", "created_by", "updated_by"]
        widgets = _date_widgets("date_from", "date_to")


class PromotionForm(PropertyModelForm):
    class Meta:
        model = Promotion
        exclude = ["property", "created_by", "updated_by", "uses"]
        widgets = {
            **_date_widgets("valid_from", "valid_to", "stay_from", "stay_to"),
            "rate_plans": forms.CheckboxSelectMultiple,
        }


class PolicyForm(PropertyModelForm):
    class Meta:
        model = CancellationPolicy
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            f: forms.Textarea(attrs={"rows": 2}) for f in ["description", "description_en", "description_pt"]
        }


plan_crud = Crud(
    model=RatePlan,
    module="rates",
    form_class=RatePlanForm,
    columns=[
        (_("Código"), "code"),
        (_("Nombre"), "name"),
        (_("Tipo"), "kind"),
        (_("Alimentación"), "meal_plan"),
        (_("Moneda"), "currency_id"),
        (_("Derivada de"), "base_plan"),
        (_("Ajuste %"), "adjustment_percent"),
        (_("Activo"), "is_active"),
    ],
    search=["code", "name"],
    filters=["kind", "is_active"],
    select_related=["base_plan"],
)
season_crud = Crud(
    model=Season,
    module="rates",
    form_class=SeasonForm,
    columns=[
        (_("Nombre"), "name"),
        (_("Tipo"), "kind"),
        (_("Desde"), "start_date"),
        (_("Hasta"), "end_date"),
        (_("Prioridad"), "priority"),
        (_("Mín. noches"), "min_nights"),
    ],
    search=["name"],
    filters=["kind"],
)
price_crud = Crud(
    model=RatePrice,
    module="rates",
    columns=[
        (_("Plan"), "rate_plan"),
        (_("Tipo"), "room_type"),
        (_("Temporada"), lambda o: o.season or _("Todo el año")),
        (_("Precio"), "price"),
        (_("Adulto extra"), "extra_adult"),
        (_("Niño"), "child"),
        (_("Cama extra"), "extra_bed"),
    ],
    filters=["rate_plan", "room_type", "season"],
    select_related=["rate_plan", "room_type", "season"],
)
restriction_crud = Crud(
    model=DateRestriction,
    module="rates",
    form_class=RestrictionForm,
    columns=[
        (_("Desde"), "date_from"),
        (_("Hasta"), "date_to"),
        (_("Tipo"), "room_type"),
        (_("Plan"), "rate_plan"),
        (_("Mín. noches"), "min_nights"),
        (_("Cerrado llegada"), "closed_to_arrival"),
        (_("Cerrado salida"), "closed_to_departure"),
        (_("Sin venta"), "stop_sell"),
    ],
    select_related=["room_type", "rate_plan"],
)
promo_crud = Crud(
    model=Promotion,
    module="rates",
    form_class=PromotionForm,
    columns=[
        (_("Código"), "code"),
        (_("Nombre"), "name"),
        (_("Descuento %"), "discount_percent"),
        (_("Válido hasta"), "valid_to"),
        (_("Usos"), "uses"),
        (_("Activa"), "is_active"),
    ],
    search=["code", "name"],
)
policy_crud = Crud(
    model=CancellationPolicy,
    module="rates",
    form_class=PolicyForm,
    columns=[
        (_("Nombre"), "name"),
        (_("Gratis hasta (días)"), "free_until_days"),
        (_("Penalidad"), "penalty"),
        (_("No show"), "no_show_penalty"),
        (_("No reembolsable"), "is_non_refundable"),
    ],
)


@require_perm("rates.view")
def calendar(request):
    """Tarifa vigente por día y tipo de habitación para un plan (14 días)."""
    plans = RatePlan.objects.filter(property=request.property, is_active=True)
    plan = plans.filter(pk=request.GET.get("plan")).first() or plans.first()
    start = timezone.localdate()
    try:
        start = timezone.datetime.fromisoformat(request.GET["start"]).date()
    except (KeyError, ValueError):
        pass
    days = [start + timedelta(days=i) for i in range(14)]
    rows = []
    if plan:
        for rt in RoomType.objects.filter(property=request.property, is_active=True):
            cells = []
            for d in days:
                q = quote(
                    plan, rt, d, d + timedelta(days=1), adults=rt.base_occupancy, check_restrictions=False
                )
                cells.append(q.nights[0].amount if q.ok and q.nights else None)
            rows.append({"room_type": rt, "cells": cells})
    return render(
        request,
        "rates/calendar.html",
        {
            "plans": plans,
            "plan": plan,
            "days": days,
            "rows": rows,
            "prev": start - timedelta(days=14),
            "next": start + timedelta(days=14),
        },
    )
