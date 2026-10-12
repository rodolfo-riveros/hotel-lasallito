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
- La CI de GitHub usa Python 3.12.
- **Sin Docker** (decisión del usuario, 2026-10-12): se ejecuta con un entorno virtual de Python
  (`.venv`) directamente en Windows. RNF-MAN-04 queda cubierto por la CI de GitHub Actions.

**Motivo.** Es más simple de mantener que microservicios y suficiente para el volumen (sección 8).
