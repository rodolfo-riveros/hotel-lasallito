from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.crud import Crud
from apps.core.models import AuditLog
from apps.guests.models import Guest
from apps.rates.services import quote
from apps.rooms.models import Room, RoomBlock

from . import services
from .availability import availability_grid
from .forms import AllotmentFormSet, CancelForm, GroupForm, ReservationForm, WaitlistForm
from .models import GroupBlock, Reservation, WaitlistEntry

waitlist_crud = Crud(
    model=WaitlistEntry,
    module="reservations",
    form_class=WaitlistForm,
    columns=[
        (gettext_lazy("Huésped"), "guest_name"),
        (gettext_lazy("Contacto"), "contact"),
        (gettext_lazy("Tipo"), "room_type"),
        (gettext_lazy("Llegada"), "arrival"),
        (gettext_lazy("Salida"), "departure"),
        (gettext_lazy("Atendida"), "resolved"),
    ],
    search=["guest_name", "contact"],
    filters=["resolved"],
    select_related=["room_type"],
    help_text=gettext_lazy("Solicitudes sin disponibilidad (RF-RES-08)."),
)


def _get(request, pk) -> Reservation:
    return get_object_or_404(
        Reservation.objects.select_related("guest", "room", "room_type", "rate_plan", "company", "group"),
        pk=pk,
        property=request.property,
    )


@require_perm("reservations.view")
def reservation_list(request):
    qs = Reservation.objects.filter(property=request.property).select_related("guest", "room", "room_type")
    q = request.GET.get("q", "").strip()
    if q:
        # RNF-REN-01: primero los huéspedes que coinciden (tabla chica, con índice de trigramas en
        # PostgreSQL) y luego sus reservas por id; el JOIN con LIKE en cuatro columnas recorría todo
        # el historial.
        from apps.guests.models import Guest

        guest_ids = Guest.objects.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q)).values("pk")
        qs = qs.filter(Q(code__icontains=q) | Q(external_ref__icontains=q) | Q(guest_id__in=guest_ids))
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    arrival = request.GET.get("arrival")
    if arrival:
        qs = qs.filter(arrival=arrival)
    page = Paginator(qs.order_by("-arrival", "-pk"), 30).get_page(request.GET.get("page"))
    return render(
        request,
        "reservations/reservation_list.html",
        {"page": page, "q": q, "status": status, "statuses": Reservation.Status.choices},
    )


def _data_from_form(cd, guest=None) -> services.ReservationData:
    return services.ReservationData(
        guest=guest or cd["guest"],
        room_type=cd["room_type"],
        rate_plan=cd["rate_plan"],
        arrival=cd["arrival"],
        departure=cd["departure"],
        adults=cd["adults"],
        children=cd["children"] or 0,
        extra_beds=cd["extra_beds"] or 0,
        cribs=cd["cribs"] or 0,
        room=cd.get("room"),
        channel=cd["channel"],
        status=cd["status"],
        company=cd.get("company"),
        group=cd.get("group"),
        discount_percent=cd.get("discount_percent") or 0,
        discount_reason=cd.get("discount_reason") or "",
        promo_code=cd.get("promo_code") or "",
        eta=cd.get("eta"),
        special_requests=cd.get("special_requests") or "",
        notes=cd.get("notes") or "",
        guarantee=cd["guarantee"],
        deposit_required=cd.get("deposit_required") or 0,
        pref_floor=cd.get("pref_floor"),
        pref_view=cd.get("pref_view") or "",
        pref_quiet=cd.get("pref_quiet", False),
        pref_accessible=cd.get("pref_accessible", False),
    )


def _form_initial(reservation: Reservation) -> dict:
    fields = ReservationForm.base_fields
    return {f: getattr(reservation, f) for f in fields if hasattr(reservation, f)}


def _save(request, reservation=None):
    initial = _form_initial(reservation) if reservation else {}
    for key in ("guest", "arrival", "departure", "room", "room_type"):
        if request.GET.get(key):
            initial[key] = request.GET[key]
    if request.GET.get("room") and "room_type" not in request.GET:
        room = Room.objects.filter(pk=request.GET["room"], property=request.property).first()
        if room:
            initial["room_type"] = room.room_type_id
    form = ReservationForm(request.POST or None, initial=initial, property=request.property)
    if request.method == "POST" and form.is_valid():
        data = _data_from_form(form.cleaned_data)
        try:
            if reservation is None:
                reservation = services.create_reservation(
                    request.property,
                    data,
                    user=request.user,
                    allow_overbooking=form.cleaned_data["allow_overbooking"],
                )
                messages.success(request, _("Reserva %(c)s creada.") % {"c": reservation.code})
            else:
                services.update_reservation(reservation, data, user=request.user)
                messages.success(request, _("Reserva actualizada."))
            return redirect("reservations:reservation_detail", pk=reservation.pk)
        except (ValidationError, PermissionDenied) as exc:
            for msg in getattr(exc, "messages", [str(exc)]):
                form.add_error(None, msg)
    selected_guest = None
    guest_id = form["guest"].value()
    if guest_id:
        selected_guest = Guest.objects.filter(pk=guest_id).first()
    return render(
        request,
        "reservations/reservation_form.html",
        {"form": form, "object": reservation, "selected_guest": selected_guest},
    )


@require_perm("reservations.create")
def reservation_create(request):
    return _save(request)


@require_perm("reservations.edit")
def reservation_edit(request, pk):
    return _save(request, _get(request, pk))


@require_perm("reservations.view")
def quote_preview(request):
    """Cotización en vivo para el formulario (HTMX)."""
    form = ReservationForm(request.GET, property=request.property)
    form.fields["guest"].required = False
    result = None
    if form.is_valid():
        cd = form.cleaned_data
        result = quote(
            cd["rate_plan"],
            cd["room_type"],
            cd["arrival"],
            cd["departure"],
            cd["adults"],
            cd["children"] or 0,
            cd["extra_beds"] or 0,
            cd["cribs"] or 0,
            discount_percent=cd.get("discount_percent") or 0,
            promo_code=cd.get("promo_code") or "",
        )
        free = services.type_availability(
            request.property, cd["room_type"], cd["arrival"], cd["departure"], group=cd.get("group")
        )
        return render(request, "reservations/partials/quote.html", {"q": result, "free": free})
    return render(request, "reservations/partials/quote.html", {"q": None, "errors": form.errors})


@require_perm("reservations.view")
def reservation_detail(request, pk):
    r = _get(request, pk)
    from apps.frontdesk.models import RoomMove
    from apps.rooms.models import Room as RoomModel

    free = []
    if r.status in Reservation.PRE_ARRIVAL_STATUSES:
        from .availability import free_rooms

        free = free_rooms(r.property, r.arrival, r.departure, room_type=r.room_type, exclude_pk=r.pk)
    return render(
        request,
        "reservations/reservation_detail.html",
        {
            "r": r,
            "folios": r.folios.all(),
            "history": services.history(r)[:30],
            "moves": RoomMove.objects.filter(reservation=r).select_related("from_room", "to_room"),
            "free_rooms": free,
            "all_rooms": RoomModel.objects.filter(property=r.property, is_active=True).select_related(
                "room_type"
            ),
            "cancel_form": CancelForm(),
            "messages_log": r.messages.all()[:20],
        },
    )


@require_POST
@require_perm("reservations.void")
def reservation_cancel(request, pk):
    r = _get(request, pk)
    form = CancelForm(request.POST)
    if form.is_valid():
        try:
            services.cancel_reservation(
                r,
                form.cleaned_data["reason"],
                user=request.user,
                waive_penalty=form.cleaned_data["waive_penalty"],
            )
            messages.success(
                request, _("Reserva cancelada. Penalidad: S/ %(p)s") % {"p": r.cancellation_penalty}
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
    return redirect("reservations:reservation_detail", pk=r.pk)


@require_POST
@require_perm("reservations.edit")
def reservation_action(request, pk, action):
    r = _get(request, pk)
    try:
        if action == "assign":
            if request.POST.get("room"):
                room = get_object_or_404(Room, pk=request.POST["room"], property=request.property)
                services.assign_room(r, room, request.user)
            else:
                services.auto_assign(r, request.user)
            messages.success(request, _("Habitación asignada: %(n)s") % {"n": r.room.number})
        elif action == "unassign":
            services.update_reservation(r, services.data_from(r, room=None), user=request.user, reprice=False)
        elif action == "confirm":
            services.confirm_waitlist(r, request.user)
            messages.success(request, _("Reserva confirmada."))
        elif action == "no_show":
            services.mark_no_show(r, request.user)
        elif action == "resend":
            from apps.comms.services import send_event

            sent = send_event("confirmation", r, force=True)
            messages.success(request, _("Confirmación enviada (%(n)s).") % {"n": len(sent)})
        elif action == "train":
            r.train_date = request.POST.get("train_date") or None
            r.train_time = request.POST.get("train_time") or None
            r.machu_picchu_date = request.POST.get("machu_picchu_date") or None
            r.save(update_fields=["train_date", "train_time", "machu_picchu_date"])
            messages.success(request, _("Datos de tren guardados."))
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
    return redirect("reservations:reservation_detail", pk=r.pk)


@require_perm("reservations.view")
def reservation_pdf(request, pk):
    from apps.comms.services import portal_url
    from apps.core.pdf import pdf_response

    r = _get(request, pk)
    return pdf_response(
        "comms/confirmation_pdf.html",
        {"r": r, "property": r.property, "portal_url": portal_url(r)},
        f"reserva-{r.code}.pdf",
    )


# --------------------------------------------------------------------------
# Tape chart (RF-RES-02)
# --------------------------------------------------------------------------

STATUS_TONE = {
    "pending": "pending",
    "confirmed": "confirmed",
    "guaranteed": "confirmed",
    "checked_in": "occupied",
    "checked_out": "neutral",
}


@require_perm("reservations.view")
def tape_chart(request):
    try:
        start = date.fromisoformat(request.GET["start"])
    except (KeyError, ValueError):
        start = request.property.current_business_date() - timedelta(days=1)
    span = min(int(request.GET.get("days", 14) or 14), 31)
    end = start + timedelta(days=span)
    days = [start + timedelta(days=i) for i in range(span)]
    rooms = list(Room.objects.filter(property=request.property, is_active=True).select_related("room_type"))
    reservations = Reservation.objects.filter(
        property=request.property,
        room__isnull=False,
        status__in=["pending", "confirmed", "guaranteed", "checked_in", "checked_out"],
        arrival__lt=end,
        departure__gt=start,
    ).select_related("guest")
    blocks = RoomBlock.objects.filter(
        property=request.property, is_active=True, start_date__lt=end, end_date__gt=start
    )
    by_room = {room.pk: [] for room in rooms}
    for r in reservations:
        s = max(r.arrival, start)
        e = min(r.departure, end)
        by_room.setdefault(r.room_id, []).append(
            {
                "r": r,
                "col": (s - start).days + 2,
                "span": max(1, (e - s).days),
                "tone": STATUS_TONE.get(r.status, "neutral"),
                "cut_left": r.arrival < start,
                "cut_right": r.departure > end,
            }
        )
    block_rows = {}
    for b in blocks:
        s, e = max(b.start_date, start), min(b.end_date, end)
        block_rows.setdefault(b.room_id, []).append(
            {"b": b, "col": (s - start).days + 2, "span": (e - s).days}
        )
    unassigned = Reservation.objects.filter(
        property=request.property,
        room__isnull=True,
        status__in=Reservation.PRE_ARRIVAL_STATUSES,
        arrival__lt=end,
        departure__gt=start,
    ).select_related("guest", "room_type")
    grid = availability_grid(request.property, start, end)
    from apps.rooms.models import RoomType

    types = RoomType.objects.filter(property=request.property, is_active=True)
    availability = [{"type": t, "cells": [grid.get(t.pk, {}).get(d, 0) for d in days]} for t in types]
    return render(
        request,
        "reservations/tape_chart.html",
        {
            "rooms": [
                {"room": room, "bars": by_room.get(room.pk, []), "blocks": block_rows.get(room.pk, [])}
                for room in rooms
            ],
            "days": days,
            "start": start,
            "span": span,
            "prev": start - timedelta(days=7),
            "next": start + timedelta(days=7),
            "today": request.property.current_business_date(),
            "unassigned": unassigned,
            "availability": availability,
        },
    )


@require_POST
@require_perm("reservations.edit")
def tape_move(request):
    """Arrastrar y soltar: mover a otra habitación/fecha o extender la salida."""
    r = _get(request, request.POST.get("reservation"))
    room = get_object_or_404(Room, pk=request.POST.get("room"), property=request.property)
    day = date.fromisoformat(request.POST.get("date"))
    try:
        with transaction.atomic():
            if request.POST.get("mode") == "extend":
                if day < r.arrival:
                    raise ValidationError(_("La salida no puede ser antes de la llegada."))
                services.move_reservation(r, departure=day + timedelta(days=1), user=request.user)
            else:
                if r.status == Reservation.Status.CHECKED_IN and day != r.arrival:
                    raise ValidationError(_("Un huésped en casa solo puede cambiar de habitación."))
                services.move_reservation(
                    r, room=room, arrival=day, departure=day + timedelta(days=r.nights), user=request.user
                )
        return JsonResponse({"ok": True})
    except (ValidationError, PermissionDenied) as exc:
        return JsonResponse(
            {"ok": False, "error": " ".join(getattr(exc, "messages", [str(exc)]))}, status=400
        )


# --------------------------------------------------------------------------
# Grupos (RF-RES-04)
# --------------------------------------------------------------------------


@require_perm("reservations.view")
def group_list(request):
    groups = (
        GroupBlock.objects.filter(property=request.property)
        .select_related("company")
        .prefetch_related("allotments__room_type")
    )
    return render(request, "reservations/group_list.html", {"groups": groups})


@require_perm("reservations.create")
def group_edit(request, pk=None):
    group = (
        get_object_or_404(GroupBlock, pk=pk, property=request.property)
        if pk
        else GroupBlock(property=request.property)
    )
    form = GroupForm(request.POST or None, instance=group, property=request.property)
    formset = AllotmentFormSet(request.POST or None, instance=group, prefix="allot")
    for f in formset.forms:
        f.fields["room_type"].queryset = f.fields["room_type"].queryset.filter(property=request.property)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            group = form.save(commit=False)
            group.property = request.property
            group.save()
            formset.instance = group
            formset.save()
            audit.log(AuditLog.Action.UPDATE if pk else AuditLog.Action.CREATE, group)
        messages.success(request, _("Grupo guardado."))
        return redirect("reservations:group_detail", pk=group.pk)
    return render(
        request,
        "reservations/group_form.html",
        {"form": form, "formset": formset, "object": group if pk else None},
    )


@require_perm("reservations.view")
def group_detail(request, pk):
    group = get_object_or_404(GroupBlock, pk=pk, property=request.property)
    rooming = group.reservations.select_related("guest", "room", "room_type").order_by("room__number")
    pickup = []
    for a in group.allotments.select_related("room_type"):
        sold = rooming.filter(room_type=a.room_type, status__in=Reservation.ACTIVE_STATUSES).count()
        pickup.append({"a": a, "sold": sold, "pending": max(0, a.quantity - sold)})
    if request.GET.get("export") == "csv":
        import csv

        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="rooming-{group.code}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["Reserva", "Huésped", "Documento", "Tipo", "Habitación", "Llegada", "Salida", "Estado"])
        for r in rooming:
            w.writerow(
                [
                    r.code,
                    r.guest.full_name,
                    r.guest.masked_doc,
                    r.room_type,
                    r.room.number if r.room else "",
                    r.arrival,
                    r.departure,
                    r.get_status_display(),
                ]
            )
        return resp
    return render(
        request, "reservations/group_detail.html", {"group": group, "rooming": rooming, "pickup": pickup}
    )
