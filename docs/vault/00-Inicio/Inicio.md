---
fase: 0
estado: completo
tags: [inicio, indice]
---
# PMS Hotel La Sallito

Sistema de gestión hotelera (PMS) en Django para hoteles de Cusco. Es un sistema de enseñanza: la
facturación SUNAT se simula y todo lo demás funciona como un PMS real.

## Estado actual

| Fase | Alcance | Estado |
| --- | --- | --- |
| 0. Base | Django, Supabase, usuarios y roles, auditoría, diseño, idiomas | ✅ Terminada, falta aprobar el diseño |
| 1. MVP operativo | Habitaciones, tarifas, reservas, recepción, folio, caja, housekeeping, huéspedes, SUNAT simulado, reportes, **restaurante y bar** | ⏳ Siguiente |
| 2. Operación completa | Almacén, compras, recetas, mantenimiento, portal, pre-check-in, comunicaciones, pagos en línea | Pendiente |
| 3. Ventas y crecimiento | Channel manager, motor web, tours, multi-propiedad, fidelidad, pronóstico | Pendiente |
| 4. Pulido | Integraciones opcionales, PWA, pruebas de carga, manual | Pendiente |

## Mapa de notas

- Requerimientos: [[_Indice de requerimientos]] y el [[Documento de requerimientos]] completo
- Decisiones:
  - [[Decisión - Supabase como base de datos]]
  - [[Decisión - Monolito modular Django]]
  - [[Decisión - Permisos módulo por acción]]
  - [[Decisión - Auditoría inmutable]]
  - [[Decisión - Frontend sin dependencias de CDN]]
  - [[Decisión - Alcance inicial un hotel con POS en fase 1]]
- Modelo de datos: [[core]], [[accounts]]
- Bitácora: [[2026-10-12]]
- Pendientes: [[Pendientes]]
