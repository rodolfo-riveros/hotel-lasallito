"""Fase 2: agrega a los roles ya creados los permisos nuevos sin pisar otras personalizaciones."""

from django.db import migrations

GRANTS = {
    "purchasing": [("purchasing", "approve")],
    "maintenance": [("inventory", "view")],
}


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")
    for code, perms in GRANTS.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for module, action in perms:
            perm, _created = Permission.objects.get_or_create(module=module, action=action)
            role.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
