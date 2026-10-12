from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from apps.core.models import Property

from .models import PropertyAccess, Role, User


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label=_("Usuario"),
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
    password = forms.CharField(
        label=_("Contraseña"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class UserForm(forms.ModelForm):
    password = forms.CharField(
        label=_("Contraseña"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("Déjela vacía para no cambiarla. Mínimo 10 caracteres."),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "preferred_language",
            "default_property",
            "is_active",
            "must_change_password",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_property"].queryset = Property.objects.filter(is_active=True)
        if not self.instance.pk:
            self.fields["password"].required = True
            self.fields["password"].help_text = _("Mínimo 10 caracteres.")

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class PropertyAccessForm(forms.ModelForm):
    class Meta:
        model = PropertyAccess
        fields = ["property", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = Property.objects.filter(is_active=True)
        self.fields["role"].queryset = Role.objects.all()


PropertyAccessFormSet = forms.inlineformset_factory(
    User, PropertyAccess, form=PropertyAccessForm, fk_name="user", extra=1, can_delete=True
)


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["code", "name", "description", "max_discount_percent", "approval_limit"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class ForcedPasswordChangeForm(SetPasswordForm):
    pass
