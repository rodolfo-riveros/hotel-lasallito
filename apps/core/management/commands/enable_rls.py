from django.core.management.base import BaseCommand

from apps.core.db import enable_rls_on_all_tables


class Command(BaseCommand):
    help = "Activa RLS en todas las tablas del esquema public de Supabase (RF-BD-04)."

    def handle(self, *args, **options):
        tables = enable_rls_on_all_tables()
        self.stdout.write(self.style.SUCCESS(f"RLS activado en {len(tables)} tablas nuevas."))
