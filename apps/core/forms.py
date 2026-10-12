from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import AuditLog, Currency, Property, TaxRule


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = [
            "name",
            "legal_name",
            "ruc",
            "kind",
            "category_stars",
            "address",
            "district",
            "city",
            "ubigeo",
            "phone",
            "email",
            "website",
            "base_currency",
            "check_in_time",
            "check_out_time",
            "logo",
            "brand_color",
        ]
        widgets = {
            "check_in_time": forms.TimeInput(attrs={"type": "time"}),
            "check_out_time": forms.TimeInput(attrs={"type": "time"}),
            "brand_color": forms.TextInput(attrs={"type": "color"}),
        }


class ExchangeRateForm(forms.Form):
    """Registra o corrige el tipo de cambio de un día (uno por moneda y fecha)."""

    date = forms.DateField(label=_("Fecha"), widget=forms.DateInput(attrs={"type": "date"}))
    currency = forms.ModelChoiceField(label=_("Moneda"), queryset=Currency.objects.none())
    buy = forms.DecimalField(label=_("Compra"), max_digits=10, decimal_places=4, min_value=Decimal("0.0001"))
    sell = forms.DecimalField(label=_("Venta"), max_digits=10, decimal_places=4, min_value=Decimal("0.0001"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["currency"].queryset = Currency.objects.filter(is_active=True).exclude(code="PEN")

    def clean(self):
        data = super().clean()
        buy, sell = data.get("buy"), data.get("sell")
        if buy and sell and sell < buy:
            raise forms.ValidationError(_("El precio de venta no puede ser menor que el de compra."))
        return data


class TaxRuleForm(forms.ModelForm):
    class Meta:
        model = TaxRule
        fields = [
            "code",
            "name",
            "rate",
            "applies_to",
            "is_included_in_price",
            "exempt_for_non_domiciled",
            "order",
            "is_active",
        ]


class AuditFilterForm(forms.Form):
    q = forms.CharField(label=_("Objeto"), required=False)
    user = forms.CharField(label=_("Usuario"), required=False)
    action = forms.ChoiceField(
        label=_("Acción"), required=False, choices=[("", _("Todas"))] + list(AuditLog.Action.choices)
    )
    date_from = forms.DateField(
        label=_("Desde"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        label=_("Hasta"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
