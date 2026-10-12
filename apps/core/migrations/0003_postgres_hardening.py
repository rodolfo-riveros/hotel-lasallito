"""Endurecimiento propio de PostgreSQL / Supabase.

- RF-BD-03: extensión btree_gist, necesaria para la restricción de exclusión
  que impide estadías solapadas en la misma habitación (fase 1).
- RNF-SEG-03: la tabla de auditoría rechaza UPDATE y DELETE a nivel de base
  de datos, no solo en el código.

En SQLite (pruebas rápidas) estas operaciones se omiten.
"""

from django.db import migrations

AUDIT_GUARD_SQL = """
CREATE OR REPLACE FUNCTION pms_audit_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'La auditoría es inmutable (operación % no permitida)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS core_auditlog_immutable ON core_auditlog;
CREATE TRIGGER core_auditlog_immutable
    BEFORE UPDATE OR DELETE ON core_auditlog
    FOR EACH ROW EXECUTE FUNCTION pms_audit_immutable();
"""

AUDIT_GUARD_REVERSE = """
DROP TRIGGER IF EXISTS core_auditlog_immutable ON core_auditlog;
DROP FUNCTION IF EXISTS pms_audit_immutable();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
        cursor.execute(AUDIT_GUARD_SQL)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(AUDIT_GUARD_REVERSE)


class Migration(migrations.Migration):
    dependencies = [("core", "0002_currencies")]

    operations = [migrations.RunPython(forwards, backwards)]
