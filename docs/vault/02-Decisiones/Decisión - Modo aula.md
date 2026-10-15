---
fecha: 2026-10-13
fase: 3
estado: aceptada
tags: [decision, aula, simulacion]
---
# Decisión: modo aula con hoteles aislados y "restablecer" que archiva

**Contexto.** RF-SIM-01 pide un botón para restablecer los datos de práctica. RF-SIM-02 pide un hotel aislado
por alumno o grupo. La auditoría es inmutable (trigger en PostgreSQL) y muchas relaciones son `PROTECT`, así
que borrar en cascada un hotel no es posible ni deseable.

**Decisión.**
- **Restablecer** no borra: archiva el hotel (`is_active=False`, código `…-arch-AAAAMMDDhhmm`) con todo lo que
  hicieron los alumnos, y crea uno nuevo con el mismo nombre y código. Los accesos de los usuarios pasan al nuevo.
  El docente conserva la evidencia y la auditoría sigue intacta.
- Los **hoteles de práctica** copian los datos fiscales e impuestos del hotel activo y cargan los mismos datos
  de ejemplo que `seed_pms --demo`. La carga corre en un hilo aparte porque contra Supabase toma minutos.
- Nuevo rol **Docente** (`teacher`) y módulo `classroom`. El docente recibe acceso a cada hotel de práctica.
- Los **escenarios** (`apps/classroom/scenarios.py`) preparan el hotel y verifican cada paso consultando lo que
  pasó en la propiedad desde que se lanzaron. No dependen de quién lo hizo, porque cada grupo tiene su hotel.
- Los **eventos** del docente usan los servicios reales: cancelar reserva, ajuste de almacén y el simulador de
  SUNAT (`connection_down`). Este último se quitó el 2026-10-15: el docente no interviene en SUNAT.
- El **avance por alumno** sale de la auditoría: acciones, anulaciones, descuentos y cajas descuadradas.

**Riesgo.** Los hoteles archivados se acumulan. Si molestan, se pueden borrar con un script en una base de aula
separada (RF-BD-07).
