"""Duplicados, fusión y derechos ARCO de huéspedes (RF-HUE-02, RF-HUE-06)."""

from django.db import transaction
from django.db.models import Q

from apps.core import audit
from apps.core.fields import blind_index
from apps.core.models import AuditLog

from .models import Guest


def find_duplicates(*, doc_number="", email="", phone="", exclude_pk=None):
    """Perfiles que comparten documento, correo o teléfono."""
    cond = Q()
    if doc_number:
        cond |= Q(doc_hash=blind_index(doc_number))
    if email:
        cond |= Q(email__iexact=email.strip())
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) >= 7:
        cond |= Q(phone__endswith=digits[-9:])
    if not cond:
        return Guest.objects.none()
    qs = Guest.objects.filter(cond)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs


@transaction.atomic
def merge_guests(primary: Guest, duplicate: Guest) -> Guest:
    """Fusiona `duplicate` en `primary`: mueve reservas, folios y comunicaciones."""
    if primary.pk == duplicate.pk:
        return primary
    from django.apps import apps

    moved = {}
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if (
                getattr(field, "many_to_one", False)
                and field.related_model is Guest
                and model is not Guest
                and field.concrete
            ):
                manager = getattr(model, "all_objects", model._default_manager)
                count = manager.filter(**{field.name: duplicate}).update(**{field.name: primary})
                if count:
                    moved[f"{model._meta.label}.{field.name}"] = count
    for attr in [
        "email",
        "phone",
        "nationality",
        "residence_country",
        "birth_date",
        "address",
        "city",
        "tam_number",
        "peru_entry_date",
        "allergies",
        "medical_conditions",
        "preferences",
    ]:
        if not getattr(primary, attr) and getattr(duplicate, attr):
            setattr(primary, attr, getattr(duplicate, attr))
    if not primary.doc_number and duplicate.doc_number:
        primary.doc_type, primary.doc_number = duplicate.doc_type, duplicate.doc_number
    primary.tags = sorted(set(primary.tags or []) | set(duplicate.tags or []))
    primary.loyalty_points += duplicate.loyalty_points
    primary.total_stays += duplicate.total_stays
    primary.total_nights += duplicate.total_nights
    primary.total_spent += duplicate.total_spent
    primary.save()
    duplicate.merged_into = primary
    duplicate.save(update_fields=["merged_into"])
    duplicate.delete()
    audit.log(
        AuditLog.Action.UPDATE,
        primary,
        changes={"fusionado_con": duplicate.pk, "movidos": moved},
        reason="Fusión de perfiles duplicados (RF-HUE-02)",
    )
    return primary


@transaction.atomic
def anonymize(guest: Guest, reason: str) -> Guest:
    """Derecho de eliminación (Ley 29733): se borran los datos personales y se
    conserva el registro para la contabilidad y la estadística."""
    guest.first_name = "Anonimizado"
    guest.last_name = f"#{guest.pk}"
    for attr in [
        "doc_number",
        "email",
        "phone",
        "address",
        "city",
        "tam_number",
        "allergies",
        "medical_conditions",
    ]:
        setattr(guest, attr, "")
    guest.preferences = guest.notes = ""
    guest.birth_date = guest.peru_entry_date = None
    guest.marketing_consent = False
    guest.save()
    audit.log(AuditLog.Action.DELETE, guest, reason=f"Ley 29733: {reason}")
    return guest
