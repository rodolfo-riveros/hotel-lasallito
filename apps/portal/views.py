"""Portal del huésped (RF-POR-01 a 03, RF-REC-05) y libro de reclamaciones público.

Se accede con un enlace único por reserva (`portal_token`), sin usuario ni
contraseña. Está pensado para celular primero y en tres idiomas.
"""

from datetime import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core import audit
from apps.core.models import AuditLog, Property, Sequence
from apps.reservations.models import Reservation

from .models import Complaint, ServiceRequest, Survey

LANGS = ("es", "en", "pt-br")


def _lang(request, reservation=None):
    lang = request.GET.get("lang") or request.session.get("portal_lang") or (reservation.language if reservation else "es")
    lang = lang if lang in LANGS else "es"
    request.session["portal_lang"] = lang
    return lang


def _reservation(token) -> Reservation:
    r = Reservation.objects.select_related("guest", "room", "room_type", "property", "rate_plan").filter(
        portal_token=token).first()
    if r is None or r.status in ("cancelled", "no_show"):
        raise Http404
    return r


def portal_render(request, template, ctx, reservation=None):
    lang = _lang(request, reservation)
    with translation.override(lang):
        ctx.update({"lang": lang, "langs": [("es", "ES"), ("en", "EN"), ("pt-br", "PT")]})
        return render(request, template, ctx)


class PreCheckinForm(forms.Form):
    first_name = forms.CharField(label=gettext_lazy("Nombres"), max_length=100)
    last_name = forms.CharField(label=gettext_lazy("Apellidos"), max_length=100)
    doc_type = forms.ChoiceField(label=gettext_lazy("Documento"),
                                 choices=[("7", gettext_lazy("Pasaporte")), ("1", "DNI"),
                                          ("4", gettext_lazy("Carné de extranjería"))])
    doc_number = forms.CharField(label=gettext_lazy("Número de documento"), max_length=30)
    nationality = forms.CharField(label=gettext_lazy("Nacionalidad (código de país, ej. US, BR)"), max_length=2)
    birth_date = forms.DateField(label=gettext_lazy("Fecha de nacimiento"), required=False,
                                 widget=forms.DateInput(attrs={"type": "date"}))
    email = forms.EmailField(label=gettext_lazy("Correo"))
    phone = forms.CharField(label=gettext_lazy("Teléfono / WhatsApp"), max_length=30)
    peru_entry_date = forms.DateField(label=gettext_lazy("Fecha de ingreso al Perú"), required=False,
                                      widget=forms.DateInput(attrs={"type": "date"}))
    eta = forms.TimeField(label=gettext_lazy("Hora estimada de llegada"), required=False,
                          widget=forms.TimeInput(attrs={"type": "time"}))
    allergies = forms.CharField(label=gettext_lazy("Alergias o condiciones de salud"), required=False)
    document_photo = forms.ImageField(label=gettext_lazy("Foto del documento"), required=False)
    signature = forms.CharField(widget=forms.HiddenInput, required=False)
    consent = forms.BooleanField(
        label=gettext_lazy("Autorizo el tratamiento de mis datos personales según la Ley 29733 y acepto las normas del hotel")
    )


def home(request, token):
    r = _reservation(token)
    return portal_render(request, "portal/home.html", {
        "r": r, "p": r.property, "requests": r.requests.all()[:10],
        "card": getattr(r, "registration_card", None), "balance": r.balance,
        "invoices": [inv for f in r.folios.all() for inv in f.invoices.exclude(status="voided")],
    }, r)


def precheckin(request, token):
    """RF-REC-05 / RF-POR-01: pre-check-in, foto del pasaporte y firma desde el celular."""
    r = _reservation(token)
    g = r.guest
    initial = {"first_name": g.first_name, "last_name": g.last_name, "doc_type": g.doc_type, "doc_number": g.doc_number,
               "nationality": g.nationality.code, "birth_date": g.birth_date, "email": g.email, "phone": g.phone,
               "peru_entry_date": g.peru_entry_date, "eta": r.eta, "allergies": g.allergies}
    form = PreCheckinForm(request.POST or None, request.FILES or None, initial=initial)
    lang = _lang(request, r)
    if request.method == "POST":
        with translation.override(lang):
            valid = form.is_valid()
        if valid:
            cd = form.cleaned_data
            from apps.frontdesk.models import RegistrationCard

            with transaction.atomic():
                for f in ("first_name", "last_name", "doc_type", "doc_number", "birth_date", "email", "phone",
                          "peru_entry_date", "allergies"):
                    setattr(g, f, cd[f])
                g.nationality = cd["nationality"].upper()
                if not g.residence_country and g.nationality != "PE":
                    g.residence_country = g.nationality
                g.give_consent()
                g.save()
                card, _c = RegistrationCard.objects.get_or_create(reservation=r)
                card.data = {"origen": "pre-check-in en línea", "ip": request.META.get("REMOTE_ADDR")}
                if cd["signature"]:
                    card.signature = cd["signature"]
                    card.signed_at = timezone.now()
                if cd["document_photo"]:
                    card.document_photo = cd["document_photo"]
                card.terms_accepted = True
                card.save()
                r.eta = cd["eta"] or r.eta
                r.precheckin_at = timezone.now()
                r.save(update_fields=["eta", "precheckin_at"])
                audit.log(AuditLog.Action.UPDATE, r, changes={"pre_check_in": True}, property=r.property)
            with translation.override(lang):
                messages.success(request, _("¡Gracias! Su pre-check-in está completo."))
            return redirect("portal:home", token=token)
    return portal_render(request, "portal/precheckin.html", {"r": r, "form": form}, r)


@require_POST
def pay(request, token):
    """RF-POR-01: pagar el saldo con la pasarela (o el depósito requerido)."""
    from apps.payments.gateways import get_gateway
    from apps.payments.services import create_payment

    r = _reservation(token)
    amount = r.balance if r.balance > 0 else (r.deposit_required or r.total_amount)
    if amount <= 0:
        return redirect("portal:home", token=token)
    payment = create_payment(r.property, amount, f"{r.property.name} · {r.code}", reservation=r, email=r.guest.email,
                             return_url=request.build_absolute_uri(reverse("portal:home", args=[token])),
                             is_deposit=r.status != "checked_in")
    return redirect(get_gateway().checkout_url(payment))


class RequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ["kind", "notes", "requested_for"]
        widgets = {"requested_for": forms.DateTimeInput(attrs={"type": "datetime-local"})}


def service_request(request, token):
    """RF-POR-02: toallas, oxígeno, despertador, traslado..."""
    r = _reservation(token)
    if r.status not in ("checked_in", "confirmed", "guaranteed", "pending"):
        raise PermissionDenied
    lang = _lang(request, r)
    with translation.override(lang):
        form = RequestForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            sr = form.save(commit=False)
            sr.property = r.property
            sr.reservation = r
            sr.save()
            from apps.comms.services import notify_role

            target = {"cleaning": "housekeeping", "towels": "housekeeping", "maintenance": "maintenance"}.get(
                sr.kind, "receptionist")
            notify_role(r.property, target, f"{sr.get_kind_display()} · hab. {r.room.number if r.room else r.code}",
                        sr.notes, url="/portal-interno/solicitudes/")
            if sr.kind == "maintenance" and r.room:
                from apps.maintenance.services import open_work_order

                open_work_order(r.property, title=sr.notes or _("Reporte del huésped"), room=r.room, source="guest")
            messages.success(request, _("Recibimos su solicitud."))
            return redirect("portal:home", token=token)
        return portal_render(request, "portal/request.html", {"r": r, "form": form}, r)


def folio(request, token):
    """RF-POR-03: consumos y comprobantes."""
    r = _reservation(token)
    folios = r.folios.prefetch_related("charges", "payments", "invoices")
    return portal_render(request, "portal/folio.html", {"r": r, "folios": folios}, r)


def invoice_pdf(request, token, pk):
    from apps.billing.models import Invoice
    from apps.billing.pdf import invoice_pdf_bytes

    r = _reservation(token)
    inv = get_object_or_404(Invoice, pk=pk, folio__reservation=r)
    resp = HttpResponse(invoice_pdf_bytes(inv), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{inv.full_number}.pdf"'
    return resp


class SurveyForm(forms.ModelForm):
    class Meta:
        model = Survey
        fields = ["overall", "room", "cleanliness", "service", "breakfast", "would_recommend", "comments"]
        widgets = {"comments": forms.Textarea(attrs={"rows": 3})}


def survey(request, token):
    """RF-HUE-05: encuesta de satisfacción post-estadía."""
    r = Reservation.objects.select_related("guest", "property").filter(portal_token=token).first()
    if r is None:
        raise Http404
    done = hasattr(r, "survey")
    lang = _lang(request, r)
    with translation.override(lang):
        form = SurveyForm(request.POST or None)
        if request.method == "POST" and not done and form.is_valid():
            s = form.save(commit=False)
            s.reservation = r
            s.save()
            if s.overall <= 2:
                from apps.comms.services import notify_role

                notify_role(r.property, "manager", _("Encuesta negativa %(c)s") % {"c": r.code}, s.comments[:200],
                            url="/portal-interno/encuestas/", level="warning")
            done = True
        return portal_render(request, "portal/survey.html", {"r": r, "form": form, "done": done}, r)


# --------------------------------------------------------------------------
# Libro de reclamaciones (público)
# --------------------------------------------------------------------------


class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ["kind", "full_name", "doc_number", "email", "phone", "address", "amount", "description", "request"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "request": forms.Textarea(attrs={"rows": 3})}


def complaint_book(request, code):
    prop = get_object_or_404(Property, code=code, is_active=True)
    form = ComplaintForm(request.POST or None)
    created = None
    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.property = prop
        c.number = f"{datetime.now():%Y}-{Sequence.next_value(prop, 'complaint'):05d}"
        c.save()
        created = c
        from apps.comms.services import notify_role, send_message

        notify_role(prop, "manager", _("Nuevo %(k)s %(n)s") % {"k": c.get_kind_display(), "n": c.number},
                    c.description[:200], url=f"/portal-interno/reclamos/{c.pk}/", level="warning")
        send_message(prop, "email", c.email, f"Hoja de reclamación {c.number} · {prop.name}",
                     f"Registramos su {c.get_kind_display().lower()} N.° {c.number}. Le responderemos en un plazo "
                     f"máximo de 15 días hábiles.\n\nDetalle: {c.description}\nPedido: {c.request}")
        form = ComplaintForm()
    return render(request, "portal/complaint_book.html", {"p": prop, "form": form, "created": created})


# --------------------------------------------------------------------------
# Vistas internas para el personal
# --------------------------------------------------------------------------


@require_perm("frontdesk.view")
def staff_requests(request):
    if request.method == "POST":
        sr = get_object_or_404(ServiceRequest, pk=request.POST.get("request"), property=request.property)
        sr.status = request.POST.get("status", sr.status)
        sr.handled_by = request.user
        sr.save(update_fields=["status", "handled_by", "updated_at"])
        return redirect("portal:staff_requests")
    items = ServiceRequest.objects.filter(property=request.property).select_related("reservation__room",
                                                                                     "reservation__guest")[:100]
    return render(request, "portal/staff_requests.html", {"items": items, "statuses": ServiceRequest.Status.choices})


@require_perm("guests.view")
def staff_surveys(request):
    from django.db.models import Avg, Count

    qs = Survey.objects.filter(reservation__property=request.property).select_related("reservation__guest")
    stats = qs.aggregate(n=Count("pk"), overall=Avg("overall"), room=Avg("room"), clean=Avg("cleanliness"),
                         service=Avg("service"), breakfast=Avg("breakfast"))
    recommend = qs.filter(would_recommend=True).count()
    return render(request, "portal/staff_surveys.html", {"items": qs[:100], "stats": stats, "recommend": recommend})


@require_perm("guests.view")
def staff_complaints(request, pk=None):
    if pk:
        c = get_object_or_404(Complaint, pk=pk, property=request.property)
        if request.method == "POST":
            if not request.user.has_pms_perm(request.property, "guests.edit"):
                raise PermissionDenied
            c.response = request.POST.get("response", "")
            c.status = request.POST.get("status", c.status)
            if c.response and not c.responded_at:
                c.responded_at = timezone.now()
                from apps.comms.services import send_message

                send_message(c.property, "email", c.email, f"Respuesta a su reclamo {c.number}", c.response)
            c.assigned_to = request.user
            c.save()
            audit.log(AuditLog.Action.UPDATE, c, changes={"estado": c.status})
            messages.success(request, _("Reclamo actualizado."))
            return redirect("portal:staff_complaint", pk=c.pk)
        return render(request, "portal/staff_complaint.html", {"c": c, "statuses": Complaint.Status.choices})
    items = Complaint.objects.filter(property=request.property)
    return render(request, "portal/staff_complaints.html", {"items": items})
