"""Utilidades de base de datos específicas de Supabase."""

from django.db import connections


def enable_rls_on_all_tables(using="default") -> list[str]:
    """RF-BD-04: activa RLS (sin políticas) en todas las tablas del esquema public.

    Así nadie puede leerlas por la API pública de Supabase (PostgREST). Django
    se conecta como dueño de las tablas y no se ve afectado.
    """
    connection = connections[using]
    if connection.vendor != "postgresql":
        return []
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
            """)
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY;')
    return tables
