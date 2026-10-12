from datetime import timedelta

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.crud import PropertyModelForm
from apps.guests.models import Company, Guest
from apps.rates.models import RatePlan
from apps.rooms.models import Room, RoomType

from .models import GroupAllotment, GroupBlock, Reservation, WaitlistEntry


class ReservationForm(forms.Form):
    guest = forms.ModelChoiceField(label=_("Huésped titular"), queryset=Guest.objects.all())
    arrival = forms.DateField(label=_("Llegada"), widget=forms.DateInput(attrs={"type": "date"}))
    departure = forms.DateField(label=_("Salida"), widget=forms.DateInput(attrs={"type": "date"}))
    room_type = forms.ModelChoiceField(label=_("Tipo de habitación"), queryset=RoomType.objects.none())
    rate_plan = forms.ModelChoiceField(label=_("Tarifa"), queryset=RatePlan.objects.none())
    adults = forms.IntegerField(label=_("Adultos"), min_value=1, max_value=10, initial=2)
    children = forms.IntegerField(label=_("Niños"), min_value=0, max_value=10, initial=0)
    extra_beds = forms.IntegerField(label=_("Camas extra"), min_value=0, max_value=3, initial=0)
    cribs = forms.IntegerField(label=_("Cunas"), min_value=0, max_value=2, initial=0)
    room = forms.ModelChoiceField(
        label=_("Habitación (opcional)"), queryset=Room.objects.none(), required=False
    )
    status = forms.ChoiceField(
        label=_("Estado"),
        choices=[
            (k, v)
            for k, v in Reservation.Status.choices
            if k in ("quote", "waitlist", "pending", "confirmed", "guaranteed")
        ],
        initial="confirmed",
    )
    channel = forms.ChoiceField(label=_("Canal"), choices=Reservation.Channel.choices, initial="direct")
    company = forms.ModelChoiceField(
        label=_("Empresa / agencia"), queryset=Company.objects.filter(is_active=True), required=False
    )
    group = forms.ModelChoiceField(label=_("Grupo"), queryset=GroupBlock.objects.none(), required=False)
    eta = forms.TimeField(
        label=_("Hora estimada de llegada"), required=False, widget=forms.TimeInput(attrs={"type": "time"})
    )
    guarantee = forms.ChoiceField(label=_("Garantía"), choices=Reservation.Guarantee.choices, initial="none")
    deposit_required = forms.DecimalField(
        label=_("Depósito requerido"), required=False, initial=0, min_value=0
    )
    discount_percent = forms.DecimalField(
        label=_("Descuento (%)"), required=False, initial=0, min_value=0, max_value=100
    )
    discount_reason = forms.CharField(label=_("Motivo del descuento"), required=False)
    promo_code = forms.CharField(label=_("Código promocional"), required=False)
    pref_floor = forms.IntegerField(label=_("Piso preferido"), required=False)
    pref_view = forms.ChoiceField(
        label=_("Vista preferida"), choices=[("", "—"), *Room.View.choices], required=False
    )
    pref_quiet = forms.BooleanField(label=_("Zona silenciosa"), required=False)
    pref_accessible = forms.BooleanField(label=_("Requiere accesibilidad"), required=False)
    special_requests = forms.CharField(
        label=_("Solicitudes especiales"), required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    notes = forms.CharField(
        label=_("Notas internas"), required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    allow_overbooking = forms.BooleanField(label=_("Autorizar sobreventa (gerente)"), required=False)

    def __init__(self, *args, property=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.property = property
        self.fields["room_type"].queryset = RoomType.objects.filter(property=property, is_active=True)
        self.fields["rate_plan"].queryset = RatePlan.objects.filter(property=property, is_active=True)
        self.fields["room"].queryset = Room.objects.filter(property=property, is_active=True).select_related(
            "room_type"
        )
        self.fields["group"].queryset = GroupBlock.objects.filter(property=property).exclude(
            status="cancelled"
        )
        if not self.is_bound and "arrival" not in self.initial and property:
            today = property.current_business_date()
            self.initial.update(arrival=today, departure=today + timedelta(days=1))

    def clean(self):
        data = super().clean()
        if data.get("arrival") and data.get("departure") and data["departure"] <= data["arrival"]:
            self.add_error("departure", _("La salida debe ser posterior a la llegada."))
        room, rt = data.get("room"), data.get("room_type")
        if room and rt and room.room_type_id != rt.pk:
            self.add_error("room", _("La habitación no es del tipo elegido."))
        if data.get("discount_percent") and not data.get("discount_reason"):
            self.add_error("discount_reason", _("Indique el motivo del descuento."))
        return data


class CancelForm(forms.Form):
    reason = forms.CharField(label=_("Motivo"), max_length=255)
    waive_penalty = forms.BooleanField(label=_("Condonar penalidad (gerente)"), required=False)


class GroupForm(PropertyModelForm):
    class Meta:
        model = GroupBlock
        exclude = ["property", "created_by", "updated_by", "is_deleted", "deleted_at", "deleted_by"]
        widgets = {
            "arrival": forms.DateInput(attrs={"type": "date"}),
            "departure": forms.DateInput(attrs={"type": "date"}),
            "release_date": forms.DateInput(attrs={"type": "date"}),
            "contract": forms.Textarea(attrs={"rows": 3}),
        }


AllotmentFormSet = forms.inlineformset_factory(
    GroupBlock, GroupAllotment, fields=["room_type", "quantity", "rate"], extra=2, can_delete=True
)


class WaitlistForm(PropertyModelForm):
    class Meta:
        model = WaitlistEntry
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            "arrival": forms.DateInput(attrs={"type": "date"}),
            "departure": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
