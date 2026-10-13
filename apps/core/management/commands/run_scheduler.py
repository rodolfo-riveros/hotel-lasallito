"""Ejecuta las tareas periódicas para cada hotel activo.

    python manage.py run_scheduler

En Windows: Programador de tareas → Crear tarea básica → repetir cada 15 minutos →
programa `.venv\\Scripts\\python.exe`, argumentos `manage.py run_scheduler`, iniciar en la
carpeta del proyecto.
"""

from django.core.management.base import BaseCommand

from apps.core.models import Property
from apps.core.scheduler import run_all


class Command(BaseCommand):
    help = "Recordatorios 48 h, reenvío a SUNAT, preventivo, liberación de grupos y alertas de almacén."

    def handle(self, *args, **options):
        for prop in Property.objects.filter(is_active=True):
            result = run_all(prop)
            self.stdout.write(f"{prop.name}: {result}")
