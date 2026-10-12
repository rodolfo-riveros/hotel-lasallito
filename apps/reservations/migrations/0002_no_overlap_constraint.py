"""Restricción de exclusión: una habitación no puede tener dos reservas activas que se solapen.

Sección 8.3 y RF-BD-03: la regla vive en la base de datos, no solo en el código.
Usa btree_gist (migración core.0003). En SQLite (pruebas rápidas) se omite.
"""

from django.db import migrations

CREATE = """
ALTER TABLE reservations_reservation
  ADD CONSTRAINT reservation_room_no_overlap
  EXCLUDE USING gist (
    room_id WITH =,
    daterange(arrival, departure, '[)') WITH &&
  )
  WHERE (room_id IS NOT NULL
         AND NOT is_deleted
         AND status IN ('pending', 'confirmed', 'guaranteed', 'checked_in'));
"""

DROP = "ALTER TABLE reservations_reservation DROP CONSTRAINT IF EXISTS reservation_room_no_overlap;"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")
        schema_editor.execute(CREATE)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [
        ("reservations", "0001_initial"),
        ("core", "0003_postgres_hardening"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
