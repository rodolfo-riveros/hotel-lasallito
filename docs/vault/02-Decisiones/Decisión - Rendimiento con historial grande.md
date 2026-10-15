---
fecha: 2026-10-15
fase: 4
estado: aceptada
tags: [decision, rendimiento]
---
# Decisión: consultas del día por fecha de salida y búsqueda en dos pasos

**Contexto.** RNF-REN-02 pide 50 usuarios concurrentes y 100 000 reservas históricas sin degradarse. Con
`generate_history` se cargaron 100 000 reservas en una base de prueba.

**Medición inicial (una petición, sin carga):**

| Pantalla | Tiempo |
| --- | --- |
| Tablero | 1,2 s |
| Recepción | 1,1 s |
| Búsqueda por apellido | 1,2 s |

Con 50 usuarios sin pausa: 4 peticiones por segundo.

**Causas.**
- Las consultas del día filtran `llegada < X y salida > Y`. El motor usaba el índice de llegada, y como
  todo el historial cumple `llegada < hoy`, recorría las 100 000 filas.
- La búsqueda unía reservas y huéspedes con `LIKE` en cuatro columnas.

**Decisión.**
- Índice `res_prop_departure` (propiedad, salida).
- La ocupación diaria filtra en la base solo por salida (muy selectiva) y descarta la llegada en Python.
- La búsqueda busca primero los huéspedes que coinciden (tabla chica) y después sus reservas por id.
- En PostgreSQL se agregan índices de trigramas (`pg_trgm`) en nombres y código de reserva.

**Resultado (100 000 reservas, misma base):**

| Pantalla | Antes | Después |
| --- | --- | --- |
| Tablero | 1 200 ms | 155 ms |
| Recepción | 1 100 ms | 50 ms |
| Búsqueda | 1 180 ms | 190 ms |
| Rack y housekeeping | — | ~30 ms |

Con 50 usuarios a la vez y pausas de 10 s entre pantallas (`scripts/load_test.py --think 10`):
- el p95 más alto fue 0,28 s, contra metas de 1 s (búsqueda) y 2 s (pantallas);
- no hubo errores.

**Límites honestos.**
- La prueba usó SQLite y el servidor de desarrollo (un proceso). Sin pausas entre pantallas, 50 usuarios
  saturan ese servidor (16 peticiones/s).
- En producción hay que usar varios procesos (gunicorn en Linux) y repetir la prueba contra la base real.
- Contra Supabase cada consulta suma ~200 ms de red desde el Perú: ver [[Decisión - Rendimiento con base en la nube]].
