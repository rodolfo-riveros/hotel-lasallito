---
fecha: 2026-10-12
fase: 1
estado: aceptada
tags: [decision, rendimiento]
---
# Decisión: rendimiento con la base de datos en la nube

**Contexto.** Desde el Perú, Supabase us-west-2 responde en unos **200 ms por consulta**, y abrir una conexión
toma unos 2 s. RNF-REN-01 pide que las pantallas de recepción carguen en menos de 2 s.

**Decisión.**
- **Sesión firmada en cookie** (`signed_cookies`): no lee ni escribe la sesión en la base.
- **Caché en memoria** de permisos, propiedades del usuario y el propio usuario (`CachedModelBackend`).
  Se invalida subiendo una versión global cuando cambia un rol, un acceso, un usuario o una propiedad.
- **Saldos anotados** (`apps/folio/queries.py`): el saldo de reservas y folios sale en la misma consulta (sin N+1).
- **Presupuesto de consultas por pantalla** vigilado por la prueba `test_query_budget.py`.
- En desarrollo, `runserver --nothreading` reutiliza la conexión. En producción, gunicorn con `CONN_MAX_AGE`.

**Resultado.** Las consultas por pantalla bajaron así:

| Pantalla | Antes | Después |
| --- | --- | --- |
| Recepción | 24 | 6 |
| Folios | 34 | 2 |
| Rack | 13 | 5 |
| Tablero | 22 | 10 |

**Recomendación pendiente.** Crear el proyecto de Supabase en **sa-east-1 (São Paulo)**. Está más cerca del Perú
y bajaría cada consulta a unos 60–80 ms.
