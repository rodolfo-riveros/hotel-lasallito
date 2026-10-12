---
fecha: 2026-10-12
fase: 0
estado: aceptada
tags: [decision, arquitectura]
---
# Decisión: monolito modular Django

**Contexto.** La sección 8 del documento propone una app de Django por módulo.

**Decisión.**
- Django 5.2 LTS con una app por módulo bajo `apps/`.
- Configuración separada en `config/settings/{base,dev,test,prod}.py` y variables de entorno con
  django-environ.
- En desarrollo local se usa Python 3.14 (el que tiene el usuario).
- Docker y CI usan Python 3.12, como pide el documento. Celery y otras librerías tienen mejor soporte ahí.

**Motivo.** Es más simple de mantener que microservicios y suficiente para el volumen (sección 8).
