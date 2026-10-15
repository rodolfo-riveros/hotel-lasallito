import hmac
import json

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.decorators import require_perm
from apps.core.models import Property
from apps.reservations.models import Reservation

from . import services
from .adapters import get_lock, pbx_enabled
from .models import CallRecord, KeyCard


@require_perm("frontdesk.view")
def panel(request):
    prop = request.property
    form = CallForm()
    return render(
        request,
        "integrations/panel.html",
        {
            "calls": CallRecord.objects.filter(property=prop).select_related("room", "reservation")[:50],
            "cards": KeyCard.objects.filter(property=prop, status="active").select_related(
                "room", "reservation__guest"
            )[:50],
            "lock": get_lock(),
            "pbx": pbx_enabled(),
            "form": form,
            "rates": services.rates(),
        },
    )


@require_POST
@require_perm("frontdesk.edit")
def duplicate_key(request, pk):
    """Graba una tarjeta adicional (o reemplaza todas si el huésped la perdió)."""
    r = get_object_or_404(Reservation, pk=pk, property=request.property, status="checked_in")
    lost = request.POST.get("lost") == "1"
    try:
        cards = services.issue_keys(r, request.user, copies=1 if not lost else 2, replace=lost)
    except Exception as exc:  # noqa: BLE001 - falla del codificador
        messages.error(request, _("El codificador falló: %(e)s") % {"e": exc})
    else:
        messages.success(
            request, _("Tarjetas grabadas: %(c)s.") % {"c": ", ".join(c.card_ref for c in cards)}
        )
    return redirect("reservations:reservation_detail", pk=pk)


class CallForm(forms.Form):
    extension = forms.CharField(label=gettext_lazy("Anexo (habitación)"), max_length=10)
    dialed = forms.CharField(label=gettext_lazy("Número marcado"), max_length=30, initial="+1 202 555 0101")
    seconds = forms.IntegerField(label=gettext_lazy("Duración (segundos)"), min_value=1, initial=125)


@require_POST
@require_perm("frontdesk.edit")
def simulate_call(request):
    """Central de prueba: registra una llamada como lo haría el CDR de la PBX."""
    form = CallForm(request.POST)
    if form.is_valid():
        cd = form.cleaned_data
        rec = services.register_call(
            request.property,
            {
                "uniqueid": f"SIM-{timezone.now():%Y%m%d%H%M%S%f}",
                "src": cd["extension"],
                "dst": cd["dialed"],
                "start": timezone.now().isoformat(),
                "billsec": cd["seconds"],
            },
        )
        if rec is None:
            messages.error(request, _("La central está desactivada (PBX=none)."))
        elif rec.charge_id:
            messages.success(request, _("Llamada cargada al folio: %(c)s.") % {"c": rec.cost})
        else:
            messages.info(request, _("Llamada registrada sin cargo (sin huésped en casa o gratuita)."))
    return redirect("integrations:panel")


@csrf_exempt
@require_POST
def pbx_webhook(request):
    """Recibe los registros de llamada (CDR) de la central. Requiere el encabezado X-PBX-Token."""
    token = getattr(settings, "PBX_TOKEN", "")
    if not token or not hmac.compare_digest(request.headers.get("X-PBX-Token", ""), token):
        return HttpResponseForbidden("token inválido")
    try:
        payload = json.loads(request.body)
        records = payload if isinstance(payload, list) else [payload]
        prop = (
            get_object_or_404(Property, code=request.GET.get("hotel"))
            if request.GET.get("hotel")
            else (Property.objects.filter(is_active=True).order_by("pk").first())
        )
        saved = [services.register_call(prop, r) for r in records]
    except (ValueError, KeyError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "registered": sum(1 for s in saved if s is not None)})
