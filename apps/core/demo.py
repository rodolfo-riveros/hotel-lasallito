"""Datos de práctica del Hotel La Sallito (RF-SIM-01). Todo es ficticio (RF-SIM-07)."""

from datetime import date, time, timedelta
from decimal import Decimal

from django.db import transaction

D = Decimal


def _ruc(prefix10: str) -> str:
    from apps.billing.validators import ruc_check_digit

    return prefix10 + str(ruc_check_digit(prefix10))


@transaction.atomic
def load_operations(hotel, today=None):
    """Habitaciones, tarifas, conceptos, POS, series, plantillas, padrones y huéspedes de ejemplo."""
    from apps.billing.models import FakePerson, FakeTaxpayer, Series
    from apps.comms.models import MessageTemplate
    from apps.folio.models import CashRegister, Concept
    from apps.guests.models import Company, Guest
    from apps.housekeeping.models import LinenType, MinibarItem
    from apps.pos.models import MenuCategory, MenuItem, Outlet, Table
    from apps.rates.models import CancellationPolicy, RatePlan, RatePrice, Season
    from apps.rooms.models import Room, RoomType

    today = today or hotel.current_business_date()
    if hotel.business_date is None:
        hotel.business_date = today
        hotel.save(update_fields=["business_date"])

    # --- Tipos y habitaciones (RF-HAB-01/02) ---------------------------------
    types = {}
    spec = [
        ("sgl", "Simple", "Single", "Solteiro", 1, 1, 0, 1, "1 plaza y media", 18, 1),
        ("dbl", "Doble twin", "Twin", "Duplo twin", 2, 2, 1, 3, "2 camas de 1.5 plazas", 24, 2),
        ("mat", "Matrimonial", "Double", "Casal", 2, 2, 1, 3, "1 queen", 24, 3),
        ("tpl", "Triple", "Triple", "Triplo", 3, 3, 1, 4, "3 camas", 30, 4),
        ("fam", "Familiar", "Family", "Família", 4, 4, 2, 5, "1 queen + 2 twin", 38, 5),
        (
            "ste",
            "Suite Valle Sagrado",
            "Sacred Valley Suite",
            "Suíte Vale Sagrado",
            2,
            2,
            2,
            4,
            "1 king + sofá cama",
            45,
            6,
        ),
    ]
    for code, name, en, pt, base, max_ad, max_ch, max_occ, beds, m2, order in spec:
        types[code], _c = RoomType.objects.get_or_create(
            property=hotel,
            code=code,
            defaults={
                "name": name,
                "name_en": en,
                "name_pt": pt,
                "base_occupancy": base,
                "max_adults": max_ad,
                "max_children": max_ch,
                "max_occupancy": max_occ,
                "beds": beds,
                "size_m2": m2,
                "sort_order": order,
                "description": "Habitación con calefacción, agua caliente, wifi y vista a los cerros del Valle.",
                "description_en": "Heated room with hot water, wifi and views of the Sacred Valley mountains.",
                "description_pt": "Quarto com aquecimento, água quente, wifi e vista para as montanhas do Vale.",
                "amenities": "Calefacción\nWifi\nAgua caliente 24 h\nCaja fuerte\nTé de coca",
            },
        )
    layout = [
        (1, ["101", "102", "103", "104", "105", "106"], ["sgl", "sgl", "dbl", "dbl", "mat", "mat"]),
        (
            2,
            ["201", "202", "203", "204", "205", "206", "207"],
            ["dbl", "dbl", "mat", "mat", "tpl", "tpl", "fam"],
        ),
        (3, ["301", "302", "303", "304", "305"], ["mat", "mat", "fam", "ste", "ste"]),
    ]
    for floor, numbers, codes in layout:
        for i, (number, code) in enumerate(zip(numbers, codes, strict=True)):
            Room.objects.get_or_create(
                property=hotel,
                number=number,
                defaults={
                    "room_type": types[code],
                    "floor": floor,
                    "sort_order": i,
                    "view": "mountain" if floor == 3 or i % 2 else "garden",
                    "has_oxygen": code in ("ste", "fam") or floor == 3,
                    "has_balcony": floor == 3,
                    "is_accessible": number == "101",
                    "is_quiet": number.endswith(("05", "06", "07")),
                },
            )

    # --- Políticas, temporadas y tarifas (RF-TAR) -----------------------------
    flexible, _c = CancellationPolicy.objects.get_or_create(
        property=hotel,
        name="Flexible 48 h",
        defaults={
            "free_until_days": 2,
            "penalty": "first_night",
            "no_show_penalty": "first_night",
            "description": "Cancelación gratuita hasta 48 horas antes de la llegada; luego se cobra la primera noche.",
            "description_en": "Free cancellation up to 48 hours before arrival; after that, the first night is charged.",
            "description_pt": "Cancelamento grátis até 48 horas antes da chegada; depois, cobra-se a primeira noite.",
        },
    )
    strict, _c = CancellationPolicy.objects.get_or_create(
        property=hotel,
        name="Temporada alta 7 días",
        defaults={
            "free_until_days": 7,
            "penalty": "percent",
            "penalty_percent": D("50"),
            "no_show_penalty": "full",
            "description": "Gratis hasta 7 días antes; luego 50% de la estadía.",
        },
    )
    nonref, _c = CancellationPolicy.objects.get_or_create(
        property=hotel,
        name="No reembolsable",
        defaults={"is_non_refundable": True, "description": "Tarifa no reembolsable."},
    )
    year = today.year
    seasons = [
        ("Temporada baja (lluvias)", "low", date(year, 1, 5), date(year, 3, 31), 1),
        ("Temporada media", "mid", date(year, 4, 1), date(year, 4, 30), 1),
        ("Temporada alta", "high", date(year, 5, 1), date(year, 9, 30), 1),
        ("Inti Raymi", "special", date(year, 6, 20), date(year, 6, 25), 3),
        ("Fiestas Patrias", "special", date(year, 7, 26), date(year, 7, 30), 3),
        ("Temporada media (fin de año)", "mid", date(year, 10, 1), date(year, 12, 20), 1),
        ("Navidad y Año Nuevo", "special", date(year, 12, 21), date(year + 1, 1, 4), 3),
        ("Temporada baja (lluvias)", "low", date(year + 1, 1, 5), date(year + 1, 3, 31), 1),
    ]
    season_objs = {}
    for name, kind, start, end, prio in seasons:
        s, _c = Season.objects.get_or_create(
            property=hotel,
            name=name,
            start_date=start,
            defaults={
                "kind": kind,
                "end_date": end,
                "priority": prio,
                "min_nights": 2 if kind == "special" else 1,
            },
        )
        season_objs.setdefault(kind, s)
    rack, _c = RatePlan.objects.get_or_create(
        property=hotel,
        code="rack-bb",
        defaults={
            "name": "Rack con desayuno",
            "name_en": "Best available rate (breakfast)",
            "name_pt": "Tarifa balcão (café da manhã)",
            "kind": "rack",
            "meal_plan": "BB",
            "cancellation_policy": flexible,
        },
    )
    plans = [
        ("solo", "Solo alojamiento", "rack", "RO", D("-8"), flexible, 1, False, D("0")),
        ("corp", "Corporativa", "corporate", "BB", D("-12"), flexible, 1, False, D("0")),
        ("agencia", "Agencia (tarifa neta)", "agency", "BB", D("-20"), flexible, 1, False, D("10")),
        ("residente", "Residente peruano", "resident", "BB", D("-15"), flexible, 1, True, D("0")),
        ("nr", "No reembolsable", "non_refundable", "BB", D("-12"), nonref, 1, False, D("0")),
        ("larga", "Estadía larga (5+ noches)", "long_stay", "BB", D("-15"), flexible, 5, False, D("0")),
        ("mapi", "Paquete Machu Picchu", "package", "HB", D("10"), strict, 3, False, D("0")),
    ]
    for code, name, kind, meal, adj, policy, min_n, resident, commission in plans:
        RatePlan.objects.get_or_create(
            property=hotel,
            code=code,
            defaults={
                "name": name,
                "kind": kind,
                "meal_plan": meal,
                "base_plan": rack,
                "adjustment_percent": adj,
                "cancellation_policy": policy,
                "min_nights": min_n,
                "requires_peruvian_resident": resident,
                "commission_percent": commission,
                "is_public": kind not in ("agency", "corporate"),
            },
        )
    base_prices = {"sgl": 180, "dbl": 260, "mat": 280, "tpl": 360, "fam": 450, "ste": 620}
    factors = {None: D("1"), "low": D("0.85"), "mid": D("1"), "high": D("1.25"), "special": D("1.45")}
    for code, price in base_prices.items():
        for kind, factor in factors.items():
            season = season_objs.get(kind) if kind else None
            if kind and season is None:
                continue
            RatePrice.objects.get_or_create(
                property=hotel,
                rate_plan=rack,
                room_type=types[code],
                season=season,
                defaults={
                    "price": (D(price) * factor).quantize(D("1")),
                    "extra_adult": D("70"),
                    "child": D("35"),
                    "extra_bed": D("60"),
                    "crib": D("0"),
                },
            )
    # Las demás temporadas especiales/bajas comparten precio por tipo de temporada.
    for s in Season.objects.filter(property=hotel):
        if s.pk in [o.pk for o in season_objs.values()]:
            continue
        for code, price in base_prices.items():
            RatePrice.objects.get_or_create(
                property=hotel,
                rate_plan=rack,
                room_type=types[code],
                season=s,
                defaults={
                    "price": (D(price) * factors[s.kind]).quantize(D("1")),
                    "extra_adult": D("70"),
                    "child": D("35"),
                    "extra_bed": D("60"),
                },
            )

    # --- Conceptos, caja y series --------------------------------------------
    from apps.folio.services import DEFAULT_CONCEPTS, get_concept

    for code in DEFAULT_CONCEPTS:
        get_concept(hotel, code)
    for code, name, price in [
        ("oxygen", "Oxígeno (sesión)", 30),
        ("laundry", "Lavandería (kg)", 12),
        ("transfer", "Traslado aeropuerto Cusco", 120),
    ]:
        Concept.objects.filter(property=hotel, code=code).update(name=name, default_price=D(price))
    CashRegister.objects.get_or_create(property=hotel, name="Recepción")
    for doc_type, code in [
        ("01", "F001"),
        ("03", "B001"),
        ("07", "FC01"),
        ("07", "BC01"),
        ("08", "FD01"),
        ("08", "BD01"),
    ]:
        Series.objects.get_or_create(property=hotel, code=code, defaults={"doc_type": doc_type})

    # --- Restaurante y bar (RF-POS) -------------------------------------------
    fnb = Concept.objects.get(property=hotel, code="fnb")
    restaurant, _c = Outlet.objects.get_or_create(
        property=hotel, name="Restaurante Willka", defaults={"kind": "restaurant", "concept": fnb}
    )
    bar, _c = Outlet.objects.get_or_create(
        property=hotel, name="Bar Inti", defaults={"kind": "bar", "concept": fnb}
    )
    room_service, _c = Outlet.objects.get_or_create(
        property=hotel, name="Room service", defaults={"kind": "room_service", "concept": fnb}
    )
    CashRegister.objects.get_or_create(property=hotel, name="Restaurante", defaults={"outlet": restaurant})
    for i, (x, y) in enumerate(
        [(15, 20), (40, 20), (65, 20), (88, 20), (15, 60), (40, 60), (65, 60), (88, 60)], 1
    ):
        Table.objects.get_or_create(
            outlet=restaurant, number=str(i), defaults={"seats": 4 if i % 3 else 6, "pos_x": x, "pos_y": y}
        )
    for i, (x, y) in enumerate([(20, 30), (50, 30), (80, 30)], 1):
        Table.objects.get_or_create(outlet=bar, number=f"B{i}", defaults={"seats": 2, "pos_x": x, "pos_y": y})
    cats = {}
    for order, (name, en, pt) in enumerate(
        [
            ("Entradas", "Starters", "Entradas"),
            ("Fondos", "Main courses", "Pratos principais"),
            ("Postres", "Desserts", "Sobremesas"),
            ("Bebidas calientes", "Hot drinks", "Bebidas quentes"),
            ("Cócteles", "Cocktails", "Coquetéis"),
        ]
    ):
        cats[name], _c = MenuCategory.objects.get_or_create(
            property=hotel, name=name, defaults={"name_en": en, "name_pt": pt, "sort_order": order}
        )
    menu = [
        ("Entradas", "Causa limeña", "Lima-style causa", "Causa limenha", 28, "kitchen", "huevo"),
        ("Entradas", "Sopa de quinua", "Quinoa soup", "Sopa de quinoa", 24, "kitchen", ""),
        (
            "Entradas",
            "Choclo con queso andino",
            "Andean corn with cheese",
            "Milho com queijo andino",
            18,
            "kitchen",
            "lácteos",
        ),
        ("Fondos", "Lomo saltado", "Stir-fried beef tenderloin", "Lombo salteado", 48, "kitchen", "soya"),
        (
            "Fondos",
            "Trucha del Urubamba a la plancha",
            "Grilled Urubamba trout",
            "Truta grelhada",
            46,
            "kitchen",
            "pescado",
        ),
        (
            "Fondos",
            "Ají de gallina",
            "Creamy chicken in yellow chili",
            "Frango ao ají amarelo",
            38,
            "kitchen",
            "lácteos, maní",
        ),
        (
            "Fondos",
            "Quinotto de hongos",
            "Mushroom quinotto",
            "Quinotto de cogumelos",
            42,
            "kitchen",
            "lácteos",
        ),
        ("Fondos", "Alpaca a la parrilla", "Grilled alpaca", "Alpaca grelhada", 58, "kitchen", ""),
        ("Postres", "Picarones", "Picarones (Andean fritters)", "Picarones", 18, "kitchen", "gluten"),
        (
            "Postres",
            "Mousse de maracuyá",
            "Passion fruit mousse",
            "Mousse de maracujá",
            16,
            "kitchen",
            "lácteos",
        ),
        ("Bebidas calientes", "Mate de coca", "Coca leaf tea", "Chá de coca", 8, "bar", ""),
        (
            "Bebidas calientes",
            "Café pasado de Quillabamba",
            "Quillabamba coffee",
            "Café de Quillabamba",
            10,
            "bar",
            "",
        ),
        (
            "Bebidas calientes",
            "Chocolate caliente andino",
            "Andean hot chocolate",
            "Chocolate quente",
            14,
            "bar",
            "lácteos",
        ),
        ("Cócteles", "Pisco sour", "Pisco sour", "Pisco sour", 28, "bar", "huevo"),
        ("Cócteles", "Chilcano de maracuyá", "Passion fruit chilcano", "Chilcano de maracujá", 26, "bar", ""),
        ("Cócteles", "Chicha morada (sin alcohol)", "Purple corn drink", "Chicha roxa", 12, "bar", ""),
    ]
    for cat, name, en, pt, price, station, allergens in menu:
        item, created = MenuItem.objects.get_or_create(
            property=hotel,
            name=name,
            defaults={
                "category": cats[cat],
                "name_en": en,
                "name_pt": pt,
                "price": D(price),
                "station": station,
                "allergens": allergens,
            },
        )
        if created:
            item.outlets.add(restaurant, room_service)
            if station == "bar":
                item.outlets.add(bar)

    # --- Housekeeping ----------------------------------------------------------
    for name, par in [
        ("Sábana 2 plazas", 120),
        ("Funda de almohada", 160),
        ("Toalla de baño", 140),
        ("Toalla de mano", 140),
        ("Bata", 40),
    ]:
        LinenType.objects.get_or_create(property=hotel, name=name, defaults={"par_level": par})
    for name, price in [
        ("Agua mineral 625 ml", 6),
        ("Cerveza Cusqueña", 12),
        ("Inca Kola", 7),
        ("Chocolate de cacao peruano", 9),
        ("Papas nativas fritas", 10),
    ]:
        MinibarItem.objects.get_or_create(property=hotel, name=name, defaults={"price": D(price)})

    # --- Plantillas de comunicación (RF-COMU-01) ------------------------------
    for event, lang, subject, body in TEMPLATES:
        MessageTemplate.objects.get_or_create(
            property=hotel,
            event=event,
            channel="email",
            language=lang,
            defaults={"subject": subject, "body": body},
        )
        MessageTemplate.objects.get_or_create(
            property=hotel,
            event=event,
            channel="whatsapp",
            language=lang,
            defaults={"subject": "", "body": body.split("\n\n")[0] + "\n{{ portal_url }}"},
        )

    # --- Padrones ficticios y clientes (sección 12) ---------------------------
    companies = [
        ("2060123456", "Andes Mining Consultores S.A.C. (ficticia)", "company", 5000, 30, 0),
        ("2060987654", "Valle Sagrado Travel E.I.R.L. (ficticia)", "agency", 8000, 15, 10),
        ("2061122334", "Inka Expeditions Operador S.A. (ficticia)", "operator", 10000, 30, 12),
        ("2059988776", "Universidad Andina de Práctica (ficticia)", "company", 3000, 30, 0),
    ]
    for prefix, name, kind, credit, days, commission in companies:
        ruc = _ruc(prefix)
        FakeTaxpayer.objects.get_or_create(
            ruc=ruc, defaults={"legal_name": name.upper(), "address": "Av. Ficticia 123, Cusco"}
        )
        Company.objects.get_or_create(
            ruc=ruc,
            defaults={
                "legal_name": name,
                "kind": kind,
                "credit_limit": D(credit),
                "credit_days": days,
                "commission_percent": D(commission),
                "email": f"reservas@{prefix}.example",
            },
        )
    for dni, first, last in [
        ("40000001", "ROSA", "HUAMÁN QUISPE"),
        ("40000002", "JULIO", "MAMANI CCORI"),
        ("40000003", "CARMEN", "TUPAC YUPANQUI"),
    ]:
        FakePerson.objects.get_or_create(dni=dni, defaults={"first_name": first, "last_name": last})

    guests = [
        (
            "Rosa",
            "Huamán Quispe",
            "1",
            "40000001",
            "PE",
            "PE",
            "es",
            "rosa.huaman@example.com",
            "+51984000001",
        ),
        (
            "Julio",
            "Mamani Ccori",
            "1",
            "40000002",
            "PE",
            "PE",
            "es",
            "julio.mamani@example.com",
            "+51984000002",
        ),
        ("Emily", "Johnson", "7", "US0000001", "US", "US", "en", "emily.j@example.com", "+12025550101"),
        ("Lucas", "Oliveira", "7", "BR0000002", "BR", "BR", "pt-br", "lucas.o@example.com", "+5511990000002"),
        ("Sophie", "Martin", "7", "FR0000003", "FR", "FR", "en", "sophie.m@example.com", "+33600000003"),
        ("Hans", "Müller", "7", "DE0000004", "DE", "DE", "en", "hans.m@example.com", "+49150000004"),
        ("Valentina", "Rossi", "7", "IT0000005", "IT", "IT", "en", "valentina.r@example.com", "+39300000005"),
        (
            "Martina",
            "González",
            "7",
            "AR0000006",
            "AR",
            "AR",
            "es",
            "martina.g@example.com",
            "+5491100000006",
        ),
        ("Diego", "Fernández", "7", "CL0000007", "CL", "CL", "es", "diego.f@example.com", "+56900000007"),
        ("Yuki", "Tanaka", "7", "JP0000008", "JP", "JP", "en", "yuki.t@example.com", "+81900000008"),
        ("Liam", "Smith", "7", "AU0000009", "AU", "AU", "en", "liam.s@example.com", "+61400000009"),
        ("Camila", "Silva", "7", "BR0000010", "BR", "BR", "pt-br", "camila.s@example.com", "+5521990000010"),
        ("Carlos", "Vargas", "4", "CE0000011", "CO", "PE", "es", "carlos.v@example.com", "+51984000011"),
        ("Ana", "Torres", "1", "40000012", "PE", "PE", "es", "ana.torres@example.com", "+51984000012"),
    ]
    created = []
    for first, last, doc_type, doc, nat, res, lang, email, phone in guests:
        g = Guest.objects.filter(email=email).first()
        if g is None:
            g = Guest.objects.create(
                first_name=first,
                last_name=last,
                doc_type=doc_type,
                doc_number=doc,
                nationality=nat,
                residence_country=res,
                language=lang,
                email=email,
                phone=phone,
                peru_entry_date=today - timedelta(days=3) if nat != "PE" else None,
                tam_number=f"TAM{doc[-6:]}" if nat != "PE" else "",
            )
            g.give_consent()
            g.save()
        created.append(g)
    created[2].tags = ["vip"]
    created[2].allergies = "Maní"
    created[2].save()
    return types, rack, created


@transaction.atomic
def load_bookings(hotel, user, guests, today=None):
    """Reservas de práctica: en casa, llegadas de hoy y futuras (RF-SIM-01)."""
    from apps.rates.models import RatePlan
    from apps.reservations.models import Reservation
    from apps.reservations.services import ReservationData, create_reservation
    from apps.rooms.models import Room, RoomType

    if Reservation.objects.filter(property=hotel).exists():
        return 0
    today = today or hotel.current_business_date()
    rack = RatePlan.objects.get(property=hotel, code="rack-bb")
    types = {t.code: t for t in RoomType.objects.filter(property=hotel)}
    rooms = {r.number: r for r in Room.objects.filter(property=hotel)}
    plan = [
        # (huésped, tipo, habitación, desde hoy, noches, check-in?)
        (2, "ste", "304", -2, 4, True),
        (3, "mat", "203", -1, 3, True),
        (4, "dbl", "103", -1, 2, True),
        (5, "mat", "105", 0, 3, False),
        (6, "dbl", "104", 0, 2, False),
        (7, "fam", "207", 0, 4, False),
        (8, "tpl", "205", 1, 2, False),
        (9, "sgl", "101", 2, 3, False),
        (10, "ste", "305", 3, 5, False),
        (11, "mat", "301", 5, 2, False),
        (0, "dbl", None, 7, 2, False),
        (1, "mat", None, 10, 3, False),
    ]
    count = 0
    for gi, tcode, rnum, offset, nights, checked_in in plan:
        arrival = today + timedelta(days=offset)
        r = create_reservation(
            hotel,
            ReservationData(
                guest=guests[gi],
                room_type=types[tcode],
                rate_plan=rack,
                arrival=arrival,
                departure=arrival + timedelta(days=nights),
                adults=2 if tcode != "sgl" else 1,
                room=rooms.get(rnum) if rnum else None,
                eta=time(10 + gi % 8, 0),
                channel=["direct", "booking", "expedia", "web", "agency", "phone"][gi % 6],
            ),
            user=user,
        )
        if checked_in:
            r.arrival = arrival
            r.status = Reservation.Status.CHECKED_IN
            r.checked_in_at = r.created_at
            r.igv_exempt = guests[gi].is_non_domiciled
            r.save()
        count += 1
    return count


TEMPLATES = [
    (
        "confirmation",
        "es",
        "Reserva {{ reservation.code }} confirmada · {{ property.name }}",
        "Hola {{ guest.first_name }}:\n\nSu reserva {{ reservation.code }} del {{ reservation.arrival|date:'d/m/Y' }} "
        "al {{ reservation.departure|date:'d/m/Y' }} está confirmada. Adjuntamos el detalle en PDF.\n\n"
        "Puede completar su pre-check-in aquí: {{ portal_url }}\n\n{{ property.name }} · Urubamba, Valle Sagrado",
    ),
    (
        "confirmation",
        "en",
        "Booking {{ reservation.code }} confirmed · {{ property.name }}",
        "Hello {{ guest.first_name }},\n\nYour booking {{ reservation.code }} from {{ reservation.arrival|date:'M d, Y' }} "
        "to {{ reservation.departure|date:'M d, Y' }} is confirmed. Details are attached as a PDF.\n\n"
        "Complete your online pre-check-in here: {{ portal_url }}\n\n{{ property.name }} · Urubamba, Sacred Valley",
    ),
    (
        "confirmation",
        "pt-br",
        "Reserva {{ reservation.code }} confirmada · {{ property.name }}",
        "Olá {{ guest.first_name }},\n\nSua reserva {{ reservation.code }} de {{ reservation.arrival|date:'d/m/Y' }} "
        "a {{ reservation.departure|date:'d/m/Y' }} está confirmada. Enviamos os detalhes em PDF.\n\n"
        "Faça seu pré-check-in aqui: {{ portal_url }}\n\n{{ property.name }} · Urubamba, Vale Sagrado",
    ),
    (
        "reminder",
        "es",
        "Le esperamos en 2 días · {{ property.name }}",
        "Hola {{ guest.first_name }}:\n\nLe esperamos el {{ reservation.arrival|date:'d/m/Y' }}. Urubamba está a 2 871 msnm: "
        "beba agua y descanse el primer día. Ahorre tiempo con el pre-check-in: {{ portal_url }}",
    ),
    (
        "reminder",
        "en",
        "See you in 2 days · {{ property.name }}",
        "Hello {{ guest.first_name }},\n\nWe look forward to welcoming you on {{ reservation.arrival|date:'M d' }}. "
        "Urubamba is 2,871 m above sea level: drink water and rest on your first day. Pre-check-in: {{ portal_url }}",
    ),
    (
        "reminder",
        "pt-br",
        "Esperamos você em 2 dias · {{ property.name }}",
        "Olá {{ guest.first_name }},\n\nEsperamos você em {{ reservation.arrival|date:'d/m' }}. Urubamba fica a 2.871 m de "
        "altitude: beba água e descanse no primeiro dia. Pré-check-in: {{ portal_url }}",
    ),
    (
        "welcome",
        "es",
        "Bienvenido a {{ property.name }}",
        "¡Bienvenido, {{ guest.first_name }}! Su habitación es la {{ reservation.room.number }}. Desde su celular puede "
        "pedir toallas, oxígeno o traslados: {{ portal_url }}",
    ),
    (
        "welcome",
        "en",
        "Welcome to {{ property.name }}",
        "Welcome, {{ guest.first_name }}! Your room is {{ reservation.room.number }}. Request towels, oxygen or transfers "
        "from your phone: {{ portal_url }}",
    ),
    (
        "welcome",
        "pt-br",
        "Bem-vindo ao {{ property.name }}",
        "Bem-vindo, {{ guest.first_name }}! Seu quarto é o {{ reservation.room.number }}. Peça toalhas, oxigênio ou "
        "traslados pelo celular: {{ portal_url }}",
    ),
    (
        "thanks",
        "es",
        "Gracias por su visita · {{ property.name }}",
        "Gracias por alojarse con nosotros, {{ guest.first_name }}. Nos ayudaría mucho su opinión: {{ survey_url }}",
    ),
    (
        "thanks",
        "en",
        "Thank you for staying with us · {{ property.name }}",
        "Thank you for staying with us, {{ guest.first_name }}. We would love your feedback: {{ survey_url }}",
    ),
    (
        "thanks",
        "pt-br",
        "Obrigado pela visita · {{ property.name }}",
        "Obrigado por se hospedar conosco, {{ guest.first_name }}. Sua opinião é muito importante: {{ survey_url }}",
    ),
    (
        "cancellation",
        "es",
        "Reserva {{ reservation.code }} cancelada",
        "Hola {{ guest.first_name }}: su reserva {{ reservation.code }} fue cancelada. "
        "Penalidad aplicada: S/ {{ reservation.cancellation_penalty }}.",
    ),
    (
        "cancellation",
        "en",
        "Booking {{ reservation.code }} cancelled",
        "Hello {{ guest.first_name }}: your booking {{ reservation.code }} has been cancelled. "
        "Penalty: PEN {{ reservation.cancellation_penalty }}.",
    ),
    (
        "cancellation",
        "pt-br",
        "Reserva {{ reservation.code }} cancelada",
        "Olá {{ guest.first_name }}: sua reserva {{ reservation.code }} foi cancelada. "
        "Multa: S/ {{ reservation.cancellation_penalty }}.",
    ),
]


@transaction.atomic
def load_phase2(hotel):
    """Almacén, recetas, proveedores y equipos de práctica (fase 2)."""
    from apps.housekeeping.models import MinibarItem
    from apps.inventory import services as inv
    from apps.inventory.models import Item, ItemCategory, RecipeLine, Warehouse
    from apps.maintenance.models import Asset, PreventivePlan
    from apps.pos.models import MenuItem, Outlet
    from apps.purchasing.models import Supplier
    from apps.rooms.models import Room

    if Warehouse.objects.filter(property=hotel).exists():
        return 0
    wh = {}
    for code, name, kind in [
        ("GEN", "Almacén general", "general"),
        ("COC", "Cocina", "kitchen"),
        ("BAR", "Bar", "bar"),
        ("HK", "Housekeeping", "housekeeping"),
        ("MAN", "Mantenimiento", "maintenance"),
    ]:
        wh[kind] = Warehouse.objects.create(property=hotel, code=code, name=name, kind=kind)
    Outlet.objects.filter(property=hotel, kind__in=["restaurant", "room_service"]).update(
        warehouse=wh["kitchen"]
    )
    Outlet.objects.filter(property=hotel, kind="bar").update(warehouse=wh["bar"])
    cats = {
        n: ItemCategory.objects.create(property=hotel, name=n)
        for n in ["Abarrotes", "Carnes y pescados", "Verduras", "Bebidas", "Amenities", "Mantenimiento"]
    }
    # (código, nombre, categoría, unidad, unidad compra, factor, mín, máx, perecible, almacén, stock, costo unitario)
    items = [
        (
            "LOMO",
            "Lomo de res",
            "Carnes y pescados",
            "g",
            "kg",
            1000,
            2000,
            8000,
            True,
            "kitchen",
            5000,
            D("0.045"),
        ),
        (
            "TRUCHA",
            "Trucha fresca",
            "Carnes y pescados",
            "g",
            "kg",
            1000,
            2000,
            6000,
            True,
            "kitchen",
            4000,
            D("0.030"),
        ),
        (
            "PAPA",
            "Papa amarilla",
            "Verduras",
            "g",
            "saco 50 kg",
            50000,
            5000,
            50000,
            True,
            "kitchen",
            20000,
            D("0.0035"),
        ),
        (
            "ARROZ",
            "Arroz",
            "Abarrotes",
            "g",
            "saco 50 kg",
            50000,
            5000,
            50000,
            False,
            "kitchen",
            25000,
            D("0.0042"),
        ),
        (
            "QUINUA",
            "Quinua",
            "Abarrotes",
            "g",
            "bolsa 5 kg",
            5000,
            2000,
            10000,
            False,
            "kitchen",
            6000,
            D("0.012"),
        ),
        (
            "PISCO",
            "Pisco quebranta",
            "Bebidas",
            "ml",
            "botella 700 ml",
            700,
            1400,
            7000,
            False,
            "bar",
            4200,
            D("0.060"),
        ),
        ("LIMON", "Limón", "Verduras", "und", "malla 100", 100, 50, 300, True, "bar", 150, D("0.20")),
        (
            "COCA",
            "Hojas de coca (bolsitas)",
            "Bebidas",
            "und",
            "caja 100",
            100,
            100,
            500,
            False,
            "bar",
            300,
            D("0.15"),
        ),
        (
            "AGUA",
            "Agua mineral 625 ml",
            "Bebidas",
            "und",
            "paquete 15",
            15,
            30,
            150,
            False,
            "housekeeping",
            60,
            D("1.80"),
        ),
        (
            "CUSQ",
            "Cerveza Cusqueña",
            "Bebidas",
            "und",
            "caja 12",
            12,
            24,
            96,
            False,
            "housekeeping",
            36,
            D("4.50"),
        ),
        (
            "SHAMP",
            "Shampoo 30 ml",
            "Amenities",
            "und",
            "caja 100",
            100,
            100,
            600,
            False,
            "housekeeping",
            250,
            D("0.90"),
        ),
        (
            "JABON",
            "Jabón 20 g",
            "Amenities",
            "und",
            "caja 100",
            100,
            100,
            600,
            False,
            "housekeeping",
            80,
            D("0.60"),
        ),
        (
            "FOCO",
            "Foco LED 9 W",
            "Mantenimiento",
            "und",
            "caja 10",
            10,
            10,
            50,
            False,
            "maintenance",
            20,
            D("6.50"),
        ),
        (
            "RESIST",
            "Resistencia de terma",
            "Mantenimiento",
            "und",
            "unidad",
            1,
            2,
            6,
            False,
            "maintenance",
            3,
            D("45.00"),
        ),
    ]
    objs = {}
    for code, name, cat, unit, pu, factor, mn, mx, perishable, kind, qty, cost in items:
        it = Item.objects.create(
            property=hotel,
            code=code,
            name=name,
            category=cats[cat],
            unit=unit,
            purchase_unit=pu,
            purchase_factor=factor,
            min_stock=mn,
            max_stock=mx,
            is_perishable=perishable,
        )
        inv.receive(
            wh[kind],
            it,
            qty,
            cost,
            kind="initial",
            reference="SALDO-INICIAL",
            lot_code="L001" if perishable else "",
            expiry=(
                hotel.current_business_date() + timedelta(days=20 if perishable else 0)
                if perishable
                else None
            ),
        )
        objs[code] = it
    recipes = {
        "Lomo saltado": [("LOMO", 180), ("PAPA", 200), ("ARROZ", 150)],
        "Trucha del Urubamba a la plancha": [("TRUCHA", 250), ("PAPA", 150)],
        "Sopa de quinua": [("QUINUA", 60), ("PAPA", 80)],
        "Pisco sour": [("PISCO", 90), ("LIMON", 1)],
        "Mate de coca": [("COCA", 1)],
    }
    for dish, lines in recipes.items():
        mi = MenuItem.objects.filter(property=hotel, name=dish).first()
        if mi:
            for code, q in lines:
                RecipeLine.objects.create(menu_item=mi, item=objs[code], quantity=q)
    MinibarItem.objects.filter(property=hotel, name__startswith="Agua").update(inventory_item=objs["AGUA"])
    MinibarItem.objects.filter(property=hotel, name__startswith="Cerveza").update(inventory_item=objs["CUSQ"])
    for prefix, name, days in [
        ("2060555111", "Distribuidora Andina de Alimentos S.A.C. (ficticia)", 15),
        ("2060555222", "Licores del Valle E.I.R.L. (ficticia)", 30),
        ("2060555333", "Ferretería Urubamba S.R.L. (ficticia)", 0),
    ]:
        Supplier.objects.create(
            property=hotel,
            ruc=_ruc(prefix),
            name=name,
            payment_days=days,
            email=f"ventas{prefix[-3:]}@example.com",
            rating=4,
        )
    rooms = list(Room.objects.filter(property=hotel)[:3])
    assets = [
        ("TER-101", "Terma eléctrica 80 L", "heater", rooms[0] if rooms else None, "", 30),
        ("CAL-01", "Caldero de agua caliente", "boiler", None, "Sala de máquinas", 90),
        ("EXT-01", "Extintor PQS 6 kg recepción", "extinguisher", None, "Recepción", 180),
        ("OXI-01", "Concentrador de oxígeno", "oxygen", None, "Recepción", 30),
    ]
    for code, name, kind, room, area, freq in assets:
        a = Asset.objects.create(
            property=hotel,
            code=code,
            name=name,
            kind=kind,
            room=room,
            area=area,
            value=D("1500"),
            acquisition_date=hotel.current_business_date() - timedelta(days=400),
        )
        PreventivePlan.objects.create(
            property=hotel,
            asset=a,
            name=f"Revisión de {name.lower()}",
            frequency_days=freq,
            next_due=hotel.current_business_date() + timedelta(days=3),
            checklist="Inspección visual\nPrueba de funcionamiento\nLimpieza",
        )
    return len(items)
