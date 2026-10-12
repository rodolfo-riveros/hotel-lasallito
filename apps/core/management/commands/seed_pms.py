"""Carga los datos iniciales del PMS.

    python manage.py seed_pms            # roles, hotel, impuestos, tipo de cambio
    python manage.py seed_pms --demo     # además, un usuario de práctica por rol

Las contraseñas de los usuarios de práctica se leen de DEMO_USER_PASSWORD
(archivo .env); nunca están escritas en el código. Todos los datos son
ficticios (RF-SIM-07).
"""

import os
from datetime import time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import PropertyAccess, Role, User
from apps.accounts.services import seed_default_roles
from apps.core.models import Currency, ExchangeRate, Property, TaxRule

DEMO_USERS = [
    ("admin", "Ana", "Quispe", "admin"),
    ("gerente", "Carlos", "Huamán", "manager"),
    ("recepcion", "Lucía", "Mamani", "receptionist"),
    ("nocturno", "Jorge", "Condori", "night_auditor"),
    ("ventas", "Rosa", "Ccori", "sales"),
    ("gobernanta", "Elena", "Tupa", "housekeeping"),
    ("mantenimiento", "Pedro", "Sutta", "maintenance"),
    ("almacen", "Miguel", "Apaza", "storekeeper"),
    ("compras", "Sofía", "Yupanqui", "purchasing"),
    ("restaurante", "Diego", "Puma", "pos"),
    ("contador", "Marta", "Inca", "accountant"),
]


class Command(BaseCommand):
    help = "Carga roles, el hotel de ejemplo, impuestos y tipo de cambio."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Crea un usuario de práctica por rol.")
        parser.add_argument(
            "--reset-roles",
            action="store_true",
            help="Restablece los permisos de los roles del sistema a sus valores por defecto.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        for code, name, symbol in [("PEN", "Sol peruano", "S/"), ("USD", "Dólar estadounidense", "US$")]:
            Currency.objects.get_or_create(code=code, defaults={"name": name, "symbol": symbol})

        roles = seed_default_roles(overwrite=options["reset_roles"])
        self.stdout.write(f"Roles: {len(roles)}")

        hotel, created = Property.objects.get_or_create(
            code="la-sallito",
            defaults={
                "name": "Hotel La Sallito",
                "legal_name": "Hotel La Sallito S.A.C. (ficticio)",
                "ruc": "20600000001",
                "kind": Property.Kind.HOTEL,
                "category_stars": 3,
                "address": "Calle Saphy 000, Cusco",
                "phone": "+51 84 000000",
                "email": "recepcion@lasallito.example",
                "check_in_time": time(14, 0),
                "check_out_time": time(11, 0),
                "base_currency_id": "PEN",
            },
        )
        self.stdout.write(f"Propiedad: {hotel} ({'creada' if created else 'ya existía'})")

        taxes = [
            {
                "code": "igv",
                "name": "IGV",
                "rate": Decimal("18.00"),
                "applies_to": TaxRule.AppliesTo.ALL,
                "exempt_for_non_domiciled": True,
                "order": 1,
                "is_active": True,
            },
            {
                "code": "servicio",
                "name": "Cargo por servicio",
                "rate": Decimal("10.00"),
                "applies_to": TaxRule.AppliesTo.FOOD_BEVERAGE,
                "exempt_for_non_domiciled": False,
                "order": 2,
                "is_active": False,
            },
        ]
        for spec in taxes:
            TaxRule.objects.get_or_create(property=hotel, code=spec["code"], defaults=spec)

        today = timezone.localdate()
        ExchangeRate.objects.get_or_create(
            date=today, currency_id="USD", defaults={"buy": Decimal("3.7400"), "sell": Decimal("3.7600")}
        )

        if options["demo"]:
            self._create_demo_users(hotel)

        self.stdout.write(self.style.SUCCESS("Datos iniciales listos."))

    def _create_demo_users(self, hotel):
        password = os.environ.get("DEMO_USER_PASSWORD")
        if not password:
            raise CommandError(
                "Defina DEMO_USER_PASSWORD en el archivo .env para crear usuarios de práctica."
            )
        roles = {r.code: r for r in Role.objects.all()}
        for username, first, last, role_code in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@lasallito.example",
                    "default_property": hotel,
                },
            )
            if created:
                user.set_password(password)
                user.save()
            PropertyAccess.objects.update_or_create(
                user=user, property=hotel, defaults={"role": roles[role_code], "is_active": True}
            )
        self.stdout.write(f"Usuarios de práctica: {len(DEMO_USERS)}")
