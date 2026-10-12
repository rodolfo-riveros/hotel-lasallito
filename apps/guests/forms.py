from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Company, Guest


class GuestForm(forms.ModelForm):
    tags = forms.MultipleChoiceField(
        label=_("Etiquetas"), choices=Guest.Tag.choices, required=False, widget=forms.CheckboxSelectMultiple
    )
    data_consent = forms.BooleanField(
        label=_("El huésped autoriza el tratamiento de sus datos personales (Ley 29733)"), required=False
    )

    class Meta:
        model = Guest
        fields = [
            "first_name",
            "last_name",
            "doc_type",
            "doc_number",
            "nationality",
            "residence_country",
            "birth_date",
            "gender",
            "email",
            "phone",
            "language",
            "address",
            "city",
            "tam_number",
            "peru_entry_date",
            "origin",
            "next_destination",
            "allergies",
            "medical_conditions",
            "preferences",
            "company",
            "tags",
            "is_blacklisted",
            "blacklist_reason",
            "marketing_consent",
            "notes",
        ]
        widgets = {
            "doc_number": forms.TextInput(),
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "peru_entry_date": forms.DateInput(attrs={"type": "date"}),
            "allergies": forms.TextInput(),
            "medical_conditions": forms.TextInput(),
            "preferences": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "company" in self.fields:
            self.fields["company"].queryset = Company.objects.filter(is_active=True)
        self.fields["data_consent"].initial = bool(self.instance.data_consent_at)

    def clean(self):
        data = super().clean()
        doc_type, doc = data.get("doc_type"), (data.get("doc_number") or "").strip()
        if doc_type == Guest.DocType.DNI and doc and (len(doc) != 8 or not doc.isdigit()):
            self.add_error("doc_number", _("El DNI tiene 8 dígitos."))
        if (
            "is_blacklisted" in self.fields
            and data.get("is_blacklisted")
            and not data.get("blacklist_reason")
        ):
            self.add_error("blacklist_reason", _("Indique el motivo."))
        data["doc_number"] = doc.upper()
        return data

    def save(self, commit=True):
        guest = super().save(commit=False)
        if self.cleaned_data.get("data_consent") and not guest.data_consent_at:
            guest.give_consent()
        if commit:
            guest.save()
        return guest


class QuickGuestForm(GuestForm):
    """Versión corta para walk-in y reservas rápidas."""

    class Meta(GuestForm.Meta):
        fields = [
            "first_name",
            "last_name",
            "doc_type",
            "doc_number",
            "nationality",
            "email",
            "phone",
            "language",
        ]


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        exclude = ["created_by", "updated_by", "is_deleted", "deleted_at", "deleted_by"]
        widgets = {"agreement": forms.Textarea(attrs={"rows": 3})}

    def clean_ruc(self):
        from apps.billing.validators import ruc_is_valid

        ruc = (self.cleaned_data.get("ruc") or "").strip()
        country = self.data.get("country") or "PE"
        if ruc and country == "PE" and not ruc_is_valid(ruc):
            raise forms.ValidationError(_("RUC inválido (dígito verificador)."))
        return ruc
