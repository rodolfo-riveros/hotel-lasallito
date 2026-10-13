---
fecha: 2026-10-13
fase: 2
estado: aceptada
tags: [decision, idiomas, operacion]
---
# Decisión: traducciones sin gettext y programador de tareas sin Redis

## Traducciones (RNF-I18N-01)
- En Windows no está GNU gettext (`makemessages` no funciona).
- Los textos que ve el huésped (portal, PDF de confirmación, estados) están en `locale/catalog.py` con su
  versión en inglés y portugués.
- `python scripts/compile_translations.py` genera los `.po` y `.mo` con `polib`.
- Para sumar un idioma: agregar la columna y el código en `LANGS`, y volver a compilar.
- Las plantillas usan `{% trans %}` normal, así que el día que haya gettext se puede migrar a `makemessages`
  sin cambiar plantillas.
- Los correos usan plantillas guardadas en la base, una por idioma.

## Tareas programadas (RNF-REN-04, RF-COMU-02, RNF-DIS-04)
- `apps/core/scheduler.py` reúne las tareas periódicas:
  - recordatorio 48 h antes de la llegada;
  - reenvío de comprobantes pendientes a SUNAT;
  - órdenes de mantenimiento preventivo;
  - liberación de cupos de grupos vencidos;
  - revisión diaria del almacén.
- Todas son idempotentes.
- Sin Redis: `python manage.py run_scheduler` cada 15 minutos con el Programador de tareas de Windows.
- Con Redis: Celery beat (`CELERY_BEAT_SCHEDULE`) llama a la misma función.
