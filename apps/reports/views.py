from datetime import date, timedelta

from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.models import AuditLog
from apps.rooms.models import RoomType

from . import services as rep
from .exports import export_table


def _range(request):
    today = request.property.current_business_date()
    try:
        start = date.fromisoformat(request.GET["start"])
    except (KeyError, ValueError):
        start = today.replace(day=1)
    try:
        end = date.fromisoformat(request.GET["end"])
    except (KeyError, ValueError):
        end = today
    if end <= start:
        end = start + timedelta(days=1)
    return start, end


REPORTS = {
    "kpis": gettext_lazy("Indicadores por día (ocupación, ADR, RevPAR)"),
    "area": gettext_lazy("Ingresos por área"),
    "channel": gettext_lazy("Ingresos por canal y agencia"),
    "country": gettext_lazy("Procedencia de huéspedes"),
    "in_house": gettext_lazy("Huéspedes en casa"),
    "arrivals": gettext_lazy("Llegadas del día"),
    "rooms": gettext_lazy("Estado de habitaciones"),
    "forecast": gettext_lazy("Pronóstico 30/60/90 vs. año anterior"),
    "mincetur": gettext_lazy("Estadística MINCETUR/DIRCETUR (arribos y pernoctaciones)"),
    "pricing": gettext_lazy("Precios sugeridos según ocupación"),
}


def build(request, key):
    prop = request.property
    start, end = _range(request)
    room_type = RoomType.objects.filter(pk=request.GET.get("room_type"), property=prop).first()
    if key == "kpis":
        data = rep.kpis(prop, start, end, room_type)
        header = [
            _("Fecha"),
            _("Disponibles"),
            _("Vendidas"),
            _("Ocupación %"),
            "ADR",
            "RevPAR",
            _("Ingreso"),
        ]
        rows = [
            [d.date.strftime("%d/%m/%Y"), d.available, d.sold, d.occupancy, d.adr, d.revpar, d.revenue]
            for d in data["days"]
        ]
        rows.append(
            [
                _("TOTAL"),
                data["available"],
                data["sold"],
                data["occupancy"],
                data["adr"],
                data["revpar"],
                data["revenue"],
            ]
        )
        return header, rows, data
    if key == "area":
        header = [_("Área"), _("Cargos"), _("Total S/")]
        return header, [[r["area"], r["n"], r["total"]] for r in rep.revenue_by_area(prop, start, end)], None
    if key == "channel":
        header = [_("Canal / agencia"), _("Reservas"), _("Noches"), _("Ingreso")]
        return (
            header,
            [
                [r["channel"], r["reservations"], r["nights"], r["revenue"]]
                for r in rep.revenue_by_channel(prop, start, end)
            ],
            rep.stay_stats(prop, start, end),
        )
    if key == "country":
        header = [_("País"), _("Huéspedes"), _("Pernoctaciones")]
        return (
            header,
            [[r["country"], r["guests"], r["nights"]] for r in rep.guests_by_country(prop, start, end)],
            None,
        )
    if key == "in_house":
        header = [_("Hab."), _("Huésped"), _("País"), _("Llegada"), _("Salida"), _("Tarifa"), _("Empresa")]
        return (
            header,
            [
                [
                    r.room.number if r.room else "",
                    r.guest.full_name,
                    r.guest.nationality.name,
                    r.arrival.strftime("%d/%m"),
                    r.departure.strftime("%d/%m"),
                    r.rate_plan.name,
                    str(r.company or ""),
                ]
                for r in rep.in_house(prop)
            ],
            None,
        )
    if key == "arrivals":
        day = prop.current_business_date()
        header = [_("Reserva"), _("Huésped"), _("Tipo"), _("Hab."), _("ETA"), _("Noches"), _("Estado")]
        return (
            header,
            [
                [
                    r.code,
                    r.guest.full_name,
                    r.room_type.code,
                    r.room.number if r.room else "",
                    r.eta.strftime("%H:%M") if r.eta else "",
                    r.nights,
                    r.get_status_display(),
                ]
                for r in rep.arrivals(prop, day)
            ],
            None,
        )
    if key == "rooms":
        from apps.core.status import ROOM
        from apps.rooms.services import room_board

        header = [_("Hab."), _("Tipo"), _("Piso"), _("Estado"), _("Huésped")]
        return (
            header,
            [
                [
                    i["room"].number,
                    i["room"].room_type.code,
                    i["room"].floor,
                    str(ROOM[i["status"]].label),
                    i["guest_reservation"].guest.full_name if i["guest_reservation"] else "",
                ]
                for i in room_board(prop)
            ],
            None,
        )
    if key == "forecast":
        header = [
            _("Días"),
            _("Ocupación %"),
            "ADR",
            _("Ingreso"),
            _("Ocup. año anterior %"),
            _("Ingreso año ant."),
            _("Diferencia pp"),
        ]
        data = rep.forecast(prop)
        return (
            header,
            [
                [
                    f["days"],
                    f["occupancy"],
                    f["adr"],
                    f["revenue"],
                    f["ly_occupancy"],
                    f["ly_revenue"],
                    f["delta"],
                ]
                for f in data
            ],
            data,
        )
    if key == "mincetur":
        data = rep.mincetur_monthly(prop, start.year, start.month)
        header = [_("Código"), _("País de residencia"), _("Arribos"), _("Pernoctaciones")]
        rows = [[r["code"], r["country"], r["arrivals"], r["overnights"]] for r in data["rows"]]
        rows.append(["", _("TOTAL"), data["total_arrivals"], data["total_overnights"]])
        return header, rows, data
    if key == "pricing":
        header = [_("Fecha"), _("Tipo"), _("Ocupación %"), _("Rack"), _("Ajuste %"), _("Sugerido")]
        return (
            header,
            [
                [
                    r["date"].strftime("%d/%m"),
                    r["room_type"].code,
                    r["occupancy"],
                    r["base"],
                    r["adjust"],
                    r["suggested"],
                ]
                for r in rep.suggested_prices(prop, 14)
            ],
            None,
        )
    raise KeyError(key)


@require_perm("reports.view")
def report_index(request):
    return render(request, "reports/index.html", {"reports": REPORTS})


@require_perm("reports.view")
def report_view(request, key):
    if key not in REPORTS:
        from django.http import Http404

        raise Http404
    start, end = _range(request)
    header, rows, extra = build(request, key)
    fmt = request.GET.get("format")
    if fmt in ("csv", "xlsx", "pdf"):
        if not request.user.has_pms_perm(request.property, "reports.export"):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        audit.log(
            AuditLog.Action.EXPORT, None, changes={"reporte": key, "formato": fmt}, property=request.property
        )
        title = f"{REPORTS[key]} · {request.property.name} · {start:%d/%m/%Y}–{end:%d/%m/%Y}"
        return export_table(title, header, rows, fmt, filename=f"{key}-{start:%Y%m%d}")
    return render(
        request,
        "reports/report.html",
        {
            "key": key,
            "title": REPORTS[key],
            "header": header,
            "rows": rows,
            "extra": extra,
            "start": start,
            "end": end,
            "room_types": RoomType.objects.filter(property=request.property, is_active=True),
        },
    )
