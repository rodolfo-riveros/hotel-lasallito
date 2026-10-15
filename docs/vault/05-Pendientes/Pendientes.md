---
tags: [pendientes]
---
# Pendientes

## Para cerrar la fase 0
- [x] Tablas antiguas de Supabase eliminadas (2026-10-12): 23 tablas vacías, 7 vistas, 12 funciones y 12 tipos
  del diseño anterior. Se conserva la extensión `pg_trgm`. Falta verificar que el esquema quedó limpio.
- [ ] El usuario conecta Supabase (`DATABASE_URL`) y corre `migrate` y `seed_pms --demo`. Luego verificar
  que la prueba del trigger de auditoría pase en PostgreSQL.
- [ ] El usuario conecta el repositorio de GitHub y confirma que la CI pasa.
- [ ] El usuario aprueba el diseño base (pantalla **Guía visual**).

## Conocidos o diferidos
- [ ] RF-SEG-03: doble factor opcional para gerencia y finanzas (TOTP). Se puede hacer en la fase 1.
- [ ] Traducciones en/pt-br (archivos `.po`). Se necesitan para el portal y los correos (fase 2). Requiere
  instalar gettext para Windows.
- [ ] Crear el bucket `pms-media` en Supabase Storage y las llaves S3 (RF-BD-06).
- [ ] Proyecto Supabase separado para producción o aula (RF-BD-07).
- [ ] Respaldos: en el plan gratuito de Supabase hay que revisar retención y pausa por inactividad (RNF-DIS-02).

## Siguiente: fase 1
Hacerlo en este orden, con aprobación del usuario antes de empezar:
1. Habitaciones y tipos.
2. Tarifas.
3. Huéspedes.
4. Reservas con tape chart y restricción de exclusión.
5. Recepción.
6. Folio y caja.
7. Facturación simulada.
8. Housekeeping.
9. Restaurante y bar.
10. Reportes.

## Después de la fase 3
- [ ] Elegir el channel manager real (SiteMinder, Cloudbeds…) y completar su adaptador (`apps/channels/adapters.py`).
- [ ] Elegir la pasarela real y completar `CulqiGateway` u otro.
- [ ] Envío programado de reportes por correo (RF-REP-06).
- [ ] Para publicar la web de reservas: definir dominio y `SITE_URL`, y fotos de los tipos de habitación.
- [ ] Base de aula separada (RF-BD-07) si los hoteles archivados se acumulan.

## Después de la fase 4 (paso a producción)
- [ ] Servidor de producción (Linux con gunicorn y varios procesos, o un PaaS) con HTTPS y dominio.
- [ ] Repetir `scripts/load_test.py` contra producción con 50 usuarios.
- [ ] Proyecto Supabase de producción/aula en una región cercana (sa-east-1) (RF-BD-07).
- [ ] Prueba mensual de restauración del respaldo (`backup_pms` + `loaddata` en una base vacía).
- [ ] Programar `run_scheduler` cada 15 minutos (Programador de tareas de Windows o cron).
- [ ] Definir `PBX_TOKEN` antes de conectar una central real, y elegir cerradura, channel manager y pasarela.
- [x] RF-FAC-06 y RF-FAC-09 terminados el 2026-10-15 (anticipos, facturación agrupada y guías de remisión).
- [ ] RNF-DIS-01/05 (disponibilidad 99,5 %, RTO/RPO) dependen del hosting elegido.
