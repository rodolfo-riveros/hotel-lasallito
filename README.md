# PMS Hotel La Sallito

PMS (Property Management System) web en Django para hoteles de Cusco, Perú. Cubre reservas, recepción,
housekeeping, restaurante, almacén, caja y facturación SUNAT. La facturación SUNAT está **simulada**
porque el sistema se usa para enseñar gestión hotelera.

La fuente de verdad es el documento de requerimientos (`docs/vault/01-Requerimientos`).

**Estado:** fase 0 (base) terminada. La siguiente es la fase 1 (MVP operativo + restaurante).

## Puesta en marcha (Windows)

Requisitos: Python 3.12 o superior y Node 20 o superior.

```bash
py -m venv .venv
.venv\Scripts\pip install -r requirements/dev.txt
npm install
npm run build
copy .env.example .env
```

Edite `.env`:

- `SECRET_KEY`: una clave larga y aleatoria.
- `DATABASE_URL`: la cadena de conexión de Supabase (vea abajo). Si la deja vacía se usa SQLite local.
- `DEMO_USER_PASSWORD`: la contraseña de los usuarios de práctica.

Luego:

```bash
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_pms --demo
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver
```

Abra http://127.0.0.1:8000. `seed_pms --demo` crea un usuario de práctica por rol: `admin`, `gerente`,
`recepcion`, `nocturno`, `ventas`, `gobernanta`, `mantenimiento`, `almacen`, `compras`, `restaurante` y
`contador`. Todos usan la contraseña `DEMO_USER_PASSWORD` de su `.env`.

## Conectar Supabase

1. En Supabase abra el proyecto y vaya a **Connect** (o *Project Settings → Database*).
2. Copie la cadena **Session pooler** (puerto 5432). Tiene esta forma:
   `postgres://postgres.<ref>:<CONTRASEÑA>@aws-0-<región>.pooler.supabase.com:5432/postgres`
3. Péguela en `DATABASE_URL` dentro de `.env`. Nunca la suba a Git.
4. Ejecute `python manage.py migrate`. La migración hace tres cosas:
   - crea las tablas;
   - activa la extensión `btree_gist`;
   - protege la tabla de auditoría para que no se pueda modificar.

   Además, después de cada migración se activa **RLS** en todas las tablas (RF-BD-04). Así nadie puede
   leerlas por la API pública de Supabase.
5. Ejecute `python manage.py seed_pms --demo`.

Si en algún momento usa el pooler en modo transacción (puerto 6543), ponga
`DB_DISABLE_SERVER_SIDE_CURSORS=True`.

## Pruebas y calidad

```bash
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\black --check .
```

Las pruebas nunca tocan Supabase. Usan `TEST_DATABASE_URL`, o SQLite en memoria si esa variable está vacía.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `config/` | Configuración de Django (`settings/base, dev, test, prod`), Celery, URLs |
| `apps/core/` | Propiedad, monedas, tipo de cambio, impuestos, auditoría, borrado lógico |
| `apps/accounts/` | Usuarios, roles, permisos módulo × acción, acceso por propiedad |
| `templates/` | Plantillas (Tailwind + HTMX + Alpine) |
| `static/src/input.css` | Componentes de diseño y colores de estado (definidos una sola vez) |
| `docs/vault/` | Bóveda de Obsidian: requerimientos, decisiones, bitácora |
