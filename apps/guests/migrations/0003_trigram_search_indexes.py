"""Índices de trigramas para buscar por nombre en PostgreSQL (RNF-REN-01).

Aceleran `icontains` en nombres de huéspedes y códigos de reserva. Usan la extensión
`pg_trgm` (ya activa en Supabase). En SQLite (pruebas) no hacen nada.
"""

from django.db import migrations

INDEXES = [
    ("guests_guest", "first_name", "guest_first_name_trgm"),
    ("guests_guest", "last_name", "guest_last_name_trgm"),
    ("reservations_reservation", "code", "reservation_code_trgm"),
]


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for table, column, name in INDEXES:
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (upper({column}) gin_trgm_ops)"
        )


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for _table, _column, name in INDEXES:
        schema_editor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0002_loyaltytier_loyaltytransaction"),
        ("reservations", "0004_departure_index"),
    ]

    operations = [migrations.RunPython(create, drop)]
