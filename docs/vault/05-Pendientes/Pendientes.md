---
tags: [pendientes]
---
# Pendientes

## Para cerrar la fase 0
- [ ] Decidir qué hacer con las 23 tablas antiguas y vacías de Supabase (`hoteles`, `reservas`, ...). Tienen
  RLS desactivado y están expuestas.
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
