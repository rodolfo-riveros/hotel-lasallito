"""Genera reservas históricas masivas para probar rendimiento (RNF-REN-02: 100 000 reservas).

Uso:  python manage.py generate_history --count 100000 --property la-sallito
Las reservas son pasadas, con estado check-out y sin habitación asignada (no ocupan inventario).
En una base remota (Supabase) exige --confirm: ocupa espacio del plan.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Property
from apps.guests.models import Guest
from apps.rates.models import RatePlan
from apps.reservations.models import Reservation
from apps.rooms.models import RoomType

FIRST = [
    "Ana",
    "Luis",
    "Emily",
    "Lucas",
    "Sophie",
    "Hans",
    "Yuki",
    "Mateo",
    "Camila",
    "Diego",
    "Liam",
    "Rosa",
]
LAST = ["Quispe", "Smith", "Silva", "Müller", "Tanaka", "Rossi", "Martin", "Mamani", "López", "Brown"]
CHANNELS = ["direct", "web", "booking", "expedia", "agency", "phone", "walk_in"]


class Command(BaseCommand):
    help = "Crea reservas históricas para pruebas de carga (RNF-REN-02)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100_000)
        parser.add_argument(
            "--property", default=None, help="Código de la propiedad (por defecto la primera)"
        )
        parser.add_argument("--guests", type=int, default=2000)
        parser.add_argument("--confirm", action="store_true", help="Necesario en bases remotas")
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **opts):
        host = settings.DATABASES["default"].get("HOST", "")
        engine = settings.DATABASES["default"]["ENGINE"]
        if "sqlite" not in engine and host not in ("", "localhost", "127.0.0.1") and not opts["confirm"]:
            raise CommandError(f"La base está en {host}. Agregue --confirm si de verdad quiere cargar ahí.")
        rnd = random.Random(opts["seed"])  # noqa: S311 - datos de prueba reproducibles, no criptografía
        prop = (
            Property.objects.filter(code=opts["property"]).first()
            if opts["property"]
            else Property.objects.order_by("pk").first()
        )
        if prop is None:
            raise CommandError("No hay propiedad.")
        types = list(RoomType.objects.filter(property=prop, is_active=True))
        plans = list(RatePlan.objects.filter(property=prop, is_active=True))
        if not types or not plans:
            raise CommandError("La propiedad necesita tipos de habitación y planes (seed_pms --demo).")

        guests = list(Guest.objects.filter(email__endswith="@historico.example")[: opts["guests"]])
        missing = opts["guests"] - len(guests)
        if missing > 0:
            Guest.objects.bulk_create(
                [
                    Guest(
                        first_name=rnd.choice(FIRST),
                        last_name=rnd.choice(LAST),
                        email=f"h{len(guests) + i}@historico.example",
                        nationality=rnd.choice(["PE", "US", "BR", "FR"]),
                        language="es",
                    )
                    for i in range(missing)
                ],
                batch_size=1000,
            )
            guests = list(Guest.objects.filter(email__endswith="@historico.example")[: opts["guests"]])

        start = Reservation.all_objects.filter(property=prop, code__startswith="H").count()
        today = prop.current_business_date()
        batch, total = [], opts["count"]
        now = timezone.now()
        for n in range(total):
            arrival = today - timedelta(days=rnd.randint(30, 365 * 6))
            nights = rnd.choice([1, 2, 2, 3, 3, 4, 5, 7])
            price = Decimal(rnd.choice([180, 220, 260, 320, 450, 620]))
            rt = rnd.choice(types)
            batch.append(
                Reservation(
                    property=prop,
                    code=f"H{start + n:07d}",
                    status="checked_out",
                    channel=rnd.choice(CHANNELS),
                    guest=rnd.choice(guests),
                    room_type=rt,
                    rate_plan=rnd.choice(plans),
                    arrival=arrival,
                    departure=arrival + timedelta(days=nights),
                    adults=rnd.randint(1, rt.max_adults),
                    currency="PEN",
                    nightly_rates=[
                        {"date": (arrival + timedelta(days=d)).isoformat(), "amount": str(price)}
                        for d in range(nights)
                    ],
                    total_amount=price * nights,
                    checked_in_at=now,
                    checked_out_at=now,
                )
            )
            if len(batch) == 2000:
                self._flush(batch)
                self.stdout.write(f"  {n + 1}/{total}")
                batch = []
        self._flush(batch)
        self.stdout.write(self.style.SUCCESS(f"{total} reservas históricas creadas en {prop}."))

    @staticmethod
    def _flush(batch):
        if batch:
            with transaction.atomic():
                Reservation.objects.bulk_create(batch, batch_size=1000)
