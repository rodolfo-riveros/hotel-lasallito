from django.core.management.base import BaseCommand

from apps.core.backup import create_backup, latest_backup, purge_old, verify


class Command(BaseCommand):
    help = "Respaldo comprimido de los datos del PMS (RNF-DIS-02). --verify prueba el último respaldo."

    def add_arguments(self, parser):
        parser.add_argument("--verify", action="store_true", help="Solo verifica el último respaldo")

    def handle(self, *args, **options):
        if options["verify"]:
            last = latest_backup()
            if last is None:
                self.stderr.write("No hay respaldos.")
                return
            self.stdout.write(f"{last.name}: {verify(last)} registros, legible.")
            return
        path = create_backup()
        self.stdout.write(self.style.SUCCESS(f"Respaldo creado: {path} ({verify(path)} registros)"))
        removed = purge_old()
        if removed:
            self.stdout.write(f"Respaldos vencidos eliminados: {removed}")
