"""Huéspedes, empresas y agencias (RF-HUE-01 a RF-HUE-07, RF-REC-03).

Los huéspedes y empresas se comparten entre las propiedades del grupo
(RF-MUL-03), por eso no llevan `property`. El número de documento, las
alergias y las condiciones médicas se guardan cifrados (RNF-SEG-04).
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField

from apps.core.fields import EncryptedTextField, blind_index
from apps.core.models import SoftDeleteModel, TimeStampedModel


class Company(TimeStampedModel, SoftDeleteModel):
    """RF-HUE-07: empresas y agencias con RUC, crédito y convenios."""

    class Kind(models.TextChoices):
        COMPANY = "company", _("Empresa")
        AGENCY = "agency", _("Agencia de viajes")
        OPERATOR = "operator", _("Operador turístico")
        OTA = "ota", _("Canal en línea (OTA)")

    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices, default=Kind.COMPANY)
    ruc = models.CharField(_("RUC / ID fiscal"), max_length=20, blank=True, db_index=True)
    legal_name = models.CharField(_("razón social"), max_length=200)
    trade_name = models.CharField(_("nombre comercial"), max_length=200, blank=True)
    address = models.CharField(_("dirección fiscal"), max_length=255, blank=True)
    country = CountryField(_("país"), default="PE")
    email = models.EmailField(_("correo"), blank=True)
    phone = models.CharField(_("teléfono"), max_length=30, blank=True)
    contact_name = models.CharField(_("contacto"), max_length=150, blank=True)
    credit_limit = models.DecimalField(_("línea de crédito (S/)"), max_digits=12, decimal_places=2, default=0)
    credit_days = models.PositiveSmallIntegerField(_("días de crédito"), default=0)
    commission_percent = models.DecimalField(_("comisión (%)"), max_digits=5, decimal_places=2, default=0)
    agreement = models.TextField(_("convenio / contrato"), blank=True)
    is_active = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("empresa o agencia")
        verbose_name_plural = _("empresas y agencias")
        ordering = ["legal_name"]

    def __str__(self):
        return self.trade_name or self.legal_name


class Guest(TimeStampedModel, SoftDeleteModel):
    """RF-HUE-01: perfil único del huésped."""

    class DocType(models.TextChoices):
        DNI = "1", _("DNI")
        CE = "4", _("Carné de extranjería")
        PASSPORT = "7", _("Pasaporte")
        OTHER = "0", _("Otro")

    class Tag(models.TextChoices):
        VIP = "vip", _("VIP")
        RECURRENT = "recurrent", _("Recurrente")
        COMPANY = "company", _("Empresa")
        AGENCY = "agency", _("Agencia")

    first_name = models.CharField(_("nombres"), max_length=100)
    last_name = models.CharField(_("apellidos"), max_length=100)
    doc_type = models.CharField(_("tipo de documento"), max_length=1, choices=DocType.choices, default="7")
    doc_number = EncryptedTextField(_("número de documento"), blank=True)
    doc_hash = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    nationality = CountryField(_("nacionalidad"), blank=True)
    residence_country = CountryField(_("país de residencia"), blank=True)
    birth_date = models.DateField(_("fecha de nacimiento"), null=True, blank=True)
    gender = models.CharField(
        _("sexo"),
        max_length=1,
        blank=True,
        choices=[("F", _("Femenino")), ("M", _("Masculino")), ("X", _("Otro"))],
    )
    email = models.EmailField(_("correo"), blank=True, db_index=True)
    phone = models.CharField(_("teléfono / WhatsApp"), max_length=30, blank=True, db_index=True)
    language = models.CharField(
        _("idioma"),
        max_length=5,
        default="es",
        choices=[("es", "Español"), ("en", "English"), ("pt-br", "Português")],
    )
    address = models.CharField(_("dirección"), max_length=255, blank=True)
    city = models.CharField(_("ciudad"), max_length=100, blank=True)
    # RF-REC-03: datos de extranjero
    tam_number = models.CharField(_("TAM (tarjeta andina)"), max_length=30, blank=True)
    peru_entry_date = models.DateField(_("fecha de ingreso al Perú"), null=True, blank=True)
    origin = models.CharField(_("procedencia"), max_length=100, blank=True)
    next_destination = models.CharField(_("próximo destino"), max_length=100, blank=True)
    # Sección 2: altura y salud
    allergies = EncryptedTextField(_("alergias"), blank=True)
    medical_conditions = EncryptedTextField(_("condiciones médicas"), blank=True)
    preferences = models.TextField(
        _("preferencias"), blank=True, help_text=_("Piso, vista, cama, almohada...")
    )
    # RF-HUE-03
    tags = models.JSONField(_("etiquetas"), default=list, blank=True)
    is_blacklisted = models.BooleanField(_("lista negra"), default=False)
    blacklist_reason = models.CharField(_("motivo de lista negra"), max_length=255, blank=True)
    company = models.ForeignKey(
        Company,
        verbose_name=_("empresa"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="guests",
    )
    # RF-HUE-06: Ley 29733
    data_consent_at = models.DateTimeField(_("consentimiento de datos"), null=True, blank=True)
    marketing_consent = models.BooleanField(_("acepta comunicaciones comerciales"), default=False)
    notes = models.TextField(_("notas internas"), blank=True)
    # Indicadores
    loyalty_points = models.IntegerField(_("puntos"), default=0)
    total_stays = models.PositiveIntegerField(_("estadías"), default=0)
    total_nights = models.PositiveIntegerField(_("noches"), default=0)
    total_spent = models.DecimalField(
        _("gasto total (S/)"), max_digits=12, decimal_places=2, default=Decimal("0")
    )
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )

    class Meta:
        verbose_name = _("huésped")
        verbose_name_plural = _("huéspedes")
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        self.doc_hash = blind_index(self.doc_number) if self.doc_number else ""
        if self.phone:
            # Formato uniforme (+51984111222) para WhatsApp y detección de duplicados.
            digits = "".join(c for c in self.phone if c.isdigit())
            self.phone = ("+" if self.phone.strip().startswith("+") else "") + digits
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_peruvian(self):
        return self.nationality == "PE" or self.doc_type == self.DocType.DNI

    @property
    def is_non_domiciled(self) -> bool:
        """Extranjero con pasaporte que no reside en el Perú (RF-TAR-06, RF-FAC-04)."""
        residence = self.residence_country.code if self.residence_country else ""
        return (
            self.doc_type == self.DocType.PASSPORT
            and bool(self.doc_number)
            and self.nationality.code not in ("", "PE")
            and residence != "PE"
        )

    @property
    def masked_doc(self) -> str:
        doc = self.doc_number or ""
        return f"{'•' * max(0, len(doc) - 4)}{doc[-4:]}" if doc else ""

    def has_tag(self, tag) -> bool:
        return tag in (self.tags or [])

    @property
    def is_vip(self):
        return self.has_tag(self.Tag.VIP)

    def give_consent(self):
        self.data_consent_at = timezone.now()


# --------------------------------------------------------------------------
# Programa de fidelidad (RF-HUE-04). Es de la cadena, como los huéspedes.
# --------------------------------------------------------------------------


class LoyaltyTier(TimeStampedModel):
    """Nivel del programa: se alcanza por puntos acumulados en toda la vida del socio."""

    name = models.CharField(_("nivel"), max_length=50)
    min_points = models.PositiveIntegerField(_("puntos acumulados para alcanzarlo"), default=0)
    earn_multiplier = models.DecimalField(
        _("multiplicador de puntos"), max_digits=4, decimal_places=2, default=Decimal("1")
    )
    discount_percent = models.DecimalField(
        _("descuento sugerido (%)"), max_digits=5, decimal_places=2, default=Decimal("0")
    )
    benefits = models.TextField(
        _("beneficios"), blank=True, help_text=_("Ej. late check-out gratis, upgrade sujeto a disponibilidad")
    )

    class Meta:
        verbose_name = _("nivel de fidelidad")
        verbose_name_plural = _("niveles de fidelidad")
        ordering = ["min_points"]

    def __str__(self):
        return self.name


class LoyaltyTransaction(TimeStampedModel):
    class Kind(models.TextChoices):
        EARN = "earn", _("Acumulación por estadía")
        REDEEM = "redeem", _("Canje")
        ADJUST = "adjust", _("Ajuste manual")
        EXPIRE = "expire", _("Vencimiento")

    guest = models.ForeignKey(
        Guest, verbose_name=_("huésped"), on_delete=models.CASCADE, related_name="loyalty_transactions"
    )
    property = models.ForeignKey(
        "core.Property", verbose_name=_("propiedad"), on_delete=models.PROTECT, related_name="+"
    )
    reservation = models.ForeignKey(
        "reservations.Reservation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(_("tipo"), max_length=10, choices=Kind.choices)
    points = models.IntegerField(_("puntos"))
    description = models.CharField(_("detalle"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("movimiento de puntos")
        verbose_name_plural = _("movimientos de puntos")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.guest} {self.points:+d}"
