"""Usuarios, roles y acceso por propiedad (RF-SEG-01, RF-SEG-02).

Un usuario puede trabajar en varias propiedades con un rol distinto en cada
una (`PropertyAccess`). El superusuario de Django tiene acceso total.
"""

from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

from .permissions import ACTIONS, MODULES_BY_CODE


class User(AbstractUser):
    email = models.EmailField(_("correo"), blank=True)
    phone = models.CharField(_("teléfono"), max_length=30, blank=True)
    preferred_language = models.CharField(
        _("idioma"),
        max_length=10,
        default="es",
        choices=[("es", "Español"), ("en", "English"), ("pt-br", "Português")],
    )
    default_property = models.ForeignKey(
        "core.Property",
        verbose_name=_("propiedad por defecto"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    must_change_password = models.BooleanField(_("debe cambiar la contraseña"), default=False)

    class Meta:
        verbose_name = _("usuario")
        verbose_name_plural = _("usuarios")
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def initials(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        if not parts:
            return self.username[:2].upper()
        return "".join(p[0] for p in parts).upper()[:2]

    # ------------------------------------------------------------------
    # Permisos del PMS
    # ------------------------------------------------------------------
    def accessible_properties(self):
        from apps.core.models import Property

        if self.is_superuser:
            return Property.objects.filter(is_active=True)
        return Property.objects.filter(
            is_active=True,
            accesses__user=self,
            accesses__is_active=True,
        ).distinct()

    def access_for(self, property_obj):
        if property_obj is None:
            return None
        cache = self.__dict__.setdefault("_pms_access_cache", {})
        if property_obj.pk not in cache:
            cache[property_obj.pk] = (
                self.property_accesses.select_related("role")
                .filter(property=property_obj, is_active=True)
                .first()
            )
        return cache[property_obj.pk]

    def pms_permissions(self, property_obj) -> frozenset[str]:
        if not self.is_active:
            return frozenset()
        if self.is_superuser:
            from .permissions import all_permission_codes

            return frozenset(all_permission_codes())
        if property_obj is None:
            return frozenset()
        memo = self.__dict__.setdefault("_pms_perm_memo", {})
        if property_obj.pk not in memo:
            from .cache import permissions_for

            memo[property_obj.pk] = permissions_for(self, property_obj.pk)[0]
        return memo[property_obj.pk]

    def has_pms_perm(self, property_obj, perm: str) -> bool:
        return perm in self.pms_permissions(property_obj)

    def role_for(self, property_obj):
        access = self.access_for(property_obj)
        return access.role if access else None


class Permission(models.Model):
    """Permiso "módulo.acción". Se sincroniza con `permissions.MODULES`."""

    module = models.CharField(_("módulo"), max_length=40)
    action = models.CharField(_("acción"), max_length=20, choices=ACTIONS)

    class Meta:
        verbose_name = _("permiso")
        verbose_name_plural = _("permisos")
        ordering = ["module", "action"]
        constraints = [models.UniqueConstraint(fields=["module", "action"], name="uniq_module_action")]

    def __str__(self):
        module = MODULES_BY_CODE.get(self.module)
        return f"{module.label if module else self.module}: {self.get_action_display()}"

    @property
    def code(self) -> str:
        return f"{self.module}.{self.action}"


class Role(TimeStampedModel):
    code = models.SlugField(_("código"), max_length=40, unique=True)
    name = models.CharField(_("nombre"), max_length=100)
    description = models.TextField(_("descripción"), blank=True)
    permissions = models.ManyToManyField(
        Permission, verbose_name=_("permisos"), blank=True, related_name="roles"
    )
    is_system = models.BooleanField(
        _("rol del sistema"),
        default=False,
        help_text=_("Creado por el sistema; se puede editar pero no eliminar."),
    )
    # RF-TAR-07: descuentos con tope por rol
    max_discount_percent = models.DecimalField(
        _("descuento máximo (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    # RF-COM-01: aprobación por monto
    approval_limit = models.DecimalField(
        _("límite de aprobación (PEN)"), max_digits=12, decimal_places=2, default=Decimal("0")
    )

    class Meta:
        verbose_name = _("rol")
        verbose_name_plural = _("roles")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def refresh_from_db(self, *args, **kwargs):
        self.__dict__.pop("_codes", None)
        super().refresh_from_db(*args, **kwargs)

    def permission_codes(self) -> frozenset[str]:
        cached = self.__dict__.get("_codes")
        if cached is None:
            cached = frozenset(f"{m}.{a}" for m, a in self.permissions.values_list("module", "action"))
            self.__dict__["_codes"] = cached
        return cached


class PropertyAccess(TimeStampedModel):
    user = models.ForeignKey(
        User, verbose_name=_("usuario"), on_delete=models.CASCADE, related_name="property_accesses"
    )
    property = models.ForeignKey(
        "core.Property", verbose_name=_("propiedad"), on_delete=models.CASCADE, related_name="accesses"
    )
    role = models.ForeignKey(Role, verbose_name=_("rol"), on_delete=models.PROTECT, related_name="accesses")
    is_active = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("acceso a propiedad")
        verbose_name_plural = _("accesos a propiedades")
        constraints = [models.UniqueConstraint(fields=["user", "property"], name="uniq_user_property_access")]

    def __str__(self):
        return f"{self.user} → {self.property} ({self.role})"
