# CLAUDE.md: PMS Hotel La Sallito

Este es un PMS hotelero en Django para hoteles de Urubamba (Valle Sagrado, Cusco). Es un sistema de enseñanza: solo la facturación SUNAT
y sus consultas (RUC, DNI, tipo de cambio) se simulan; todo lo demás funciona como un PMS real.

## Reglas de trabajo

1. Trabajar **por fases** (fase 0 → 1 → 2 → 3 → 4). No avanzar a la siguiente sin aprobación del usuario.
2. Cada requerimiento implementado lleva su **prueba automática** y se cita por su código (por ejemplo,
   `RF-RES-02`) en el docstring de la prueba o del módulo.
3. Montos siempre en `Decimal`, nunca en `float`.
4. Reservas, huéspedes y comprobantes usan **borrado lógico** (`SoftDeleteModel`).
5. **Auditoría** (`apps.core.audit.log` / `log_changes`) en descuentos, anulaciones, cambios de tarifa,
   cierres de caja, permisos y accesos a datos personales.
6. **Transacciones** (`transaction.atomic`) en reservas, pagos y comprobantes. La numeración de
   comprobantes se asigna dentro de la transacción.
7. Todo registro operativo hereda `PropertyScopedModel` (lleva `property`).
8. Las integraciones externas (SUNAT, pasarela de pagos, channel manager) van **detrás de adaptadores**.
   `SUNAT_MODE=simulator|production`.
9. Al terminar cada sesión, actualizar la bóveda `docs/vault/`:
   - nota del día en `03-Bitacora`;
   - casillas de requerimientos en `01-Requerimientos`;
   - decisiones en `02-Decisiones`;
   - modelo de datos en `04-Modelo-de-datos`.

   La bóveda se confirma en el mismo commit que el código.

## Decisiones vigentes

- Un solo hotel (Hotel La Sallito) por ahora. El modelo ya es multi-propiedad.
- El POS (restaurante y bar) entra en la **fase 1**. Las recetas que descuentan del almacén van en la fase 2.
- Pasarela de pagos y channel manager: se eligen más adelante. Por ahora, adaptador con implementación de prueba
  (`PAYMENT_GATEWAY=test`, `CHANNEL_MANAGER=test`).
- Modo aula: "restablecer" archiva el hotel y crea uno limpio; nunca se borran datos ni auditoría.
- La web pública de reservas vive en `/reservar/` (app `booking_engine`); no requiere usuario.
- Base de datos: Supabase, proyecto `hotel-lasallito` (ref `ddddqyowhshjmblixrla`, us-west-2), conectado por el pooler
  en modo sesión.

## Comandos

```bash
.venv/Scripts/python manage.py runserver --nothreading   # reutiliza la conexión a Supabase
.venv/Scripts/python manage.py seed_pms --demo    # roles, hotel de ejemplo, usuarios de práctica
.venv/Scripts/python -m pytest                    # pruebas (nunca contra Supabase)
.venv/Scripts/ruff check . && .venv/Scripts/black --check .
npm run build                                     # CSS de Tailwind + HTMX/Alpine/fuentes en static/vendor
.venv/Scripts/python manage.py run_scheduler      # tareas periódicas (programar cada 15 min)
.venv/Scripts/python scripts/compile_translations.py   # compila locale/catalog.py (en, pt_BR)
.venv/Scripts/python scripts/vault_requirements.py     # regenera casillas de requerimientos en la bóveda
.venv/Scripts/python manage.py backup_pms [--verify]   # respaldo comprimido en backups/ (30 días)
.venv/Scripts/python manage.py generate_history --count 100000   # historial para pruebas de carga (no en Supabase)
.venv/Scripts/python scripts/load_test.py --users 50 --think 10   # prueba de carga (LOAD_TEST_USER/PASSWORD)
.venv/Scripts/python -m pytest --cov --cov-config=.coveragerc-business   # cobertura de reglas de negocio (≥ 80 %)
```

Después de cambiar plantillas o clases de Tailwind: `npm run build:css`. `static/css/app.css` se versiona
para que el sistema funcione sin Node.

## Arquitectura

Es un monolito modular. Hay una app de Django por módulo (sección 8.2 del documento de requerimientos), bajo
`apps/`.

- **Permisos:** `apps/accounts/permissions.py` es el catálogo único de módulos y acciones. Las vistas usan
  `@require_perm("modulo.accion")` o `PermRequiredMixin`, y las plantillas usan `{% can "modulo.accion" as x %}`.
  El menú se arma solo a partir del catálogo.
- **Propiedad activa:** `request.property`, la fija `CurrentPropertyMiddleware`.
- **Estados y colores:**
  - textos e íconos en `apps/core/status.py`;
  - clases en `static/src/input.css` (`.status-*`);
  - colores en `tailwind.config.js` (`state`).
  - Uso en plantillas: `{% status_badge "room" "dirty" %}`.
- **Íconos:** `{% icon "nombre" %}` (`apps/core/templatetags/pms.py`).
- **Montos:** `{{ valor|money:"USD" }}`.
- **Catálogos:** `apps/core/crud.py` (`Crud(...)`) genera listas y formularios con permisos y auditoría.
- **Rendimiento:** cada consulta a Supabase cuesta ~200 ms. Use `select_related`, las anotaciones de
  `apps/folio/queries.py` y respete `test_query_budget.py`.
- **Datos de práctica:** `apps/core/demo.py` (se cargan con `seed_pms --demo`).
- **Manual de usuario:** `docs/manual/*.md`, visible en `/ayuda/` (`apps/core/help.py`). Al cambiar una pantalla,
  actualice su capítulo.
- **Historial grande:** las consultas del día filtran por `departure` (índice `res_prop_departure`), no por
  `arrival < X`, que recorre todo el historial.
