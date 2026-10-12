from django import forms

from apps.core.crud import PropertyModelForm

from .models import Room, RoomBlock, RoomType


class RoomTypeForm(PropertyModelForm):
    class Meta:
        model = RoomType
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
            "description_pt": forms.Textarea(attrs={"rows": 3}),
            "amenities": forms.Textarea(attrs={"rows": 3}),
        }


class RoomForm(PropertyModelForm):
    class Meta:
        model = Room
        exclude = ["property", "created_by", "updated_by"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "connecting_rooms": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            qs = self.fields["connecting_rooms"].queryset
            self.fields["connecting_rooms"].queryset = qs.exclude(pk=self.instance.pk)


class RoomBlockForm(PropertyModelForm):
    class Meta:
        model = RoomBlock
        fields = ["room", "kind", "start_date", "end_date", "reason", "is_active"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end <= start:
            raise forms.ValidationError("La fecha final debe ser posterior a la inicial.")
        room = data.get("room")
        if room and start and end and data.get("is_active", True):
            from apps.reservations.availability import overlapping_reservations

            conflicts = overlapping_reservations(room, start, end)
            if conflicts:
                codes = ", ".join(r.code for r in conflicts[:5])
                raise forms.ValidationError(
                    f"La habitación tiene reservas en esas fechas ({codes}). Reubíquelas antes de bloquear."
                )
        return data
