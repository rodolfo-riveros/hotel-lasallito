from django.db import transaction

from .permissions import DEFAULT_ROLES, MODULES


def sync_permissions(using="default") -> int:
    """Crea en la base los permisos "módulo.acción" declarados en el catálogo."""
    from .models import Permission

    existing = set(Permission.objects.using(using).values_list("module", "action"))
    missing = [
        Permission(module=m.code, action=a) for m in MODULES for a in m.actions if (m.code, a) not in existing
    ]
    Permission.objects.using(using).bulk_create(missing)
    return len(missing)


@transaction.atomic
def seed_default_roles(*, overwrite=False) -> list:
    """Crea los roles de la sección 3. Sin `overwrite` respeta los ya editados."""
    from .models import Permission, Role

    sync_permissions()
    by_code = {p.code: p for p in Permission.objects.all()}
    roles = []
    for spec in DEFAULT_ROLES:
        role, created = Role.objects.get_or_create(
            code=spec["code"],
            defaults={
                "name": str(spec["name"]),
                "description": str(spec["description"]),
                "is_system": True,
                "max_discount_percent": spec.get("max_discount_percent", 0),
                "approval_limit": spec.get("approval_limit", 0),
            },
        )
        if created or overwrite:
            role.permissions.set([by_code[c] for c in spec["permissions"]])
        roles.append(role)
    return roles
