# Administración y seguridad

## Usuarios y roles

**Usuarios y roles** (`g` `u`):

- Cree el usuario y asígnele un **rol por hotel** (puede tener roles distintos en cada hotel).
- Los roles definen qué puede ver, crear, editar, anular, aprobar y exportar en cada módulo, y el tope de descuento.
- Roles incluidos: administrador, gerente, recepcionista, night auditor, ventas, housekeeping, mantenimiento, almacén, compras, restaurante, contador y docente.

## Doble factor

Cada usuario lo activa desde **Mi cuenta** (ícono del candado):

1. Instale Google Authenticator, Microsoft Authenticator o Authy en el celular.
2. Escanee el código QR y escriba el código para confirmar.

Desde entonces, al ingresar se pide el código. Se recomienda para gerencia y finanzas; el administrador puede volverlo obligatorio por rol (`TWO_FACTOR_REQUIRED_ROLES`). Si alguien pierde el celular, el administrador abre su usuario y pulsa **Reiniciar doble factor**.

## Configuración del hotel

**Configuración:** datos fiscales, horarios de check-in y check-out, cargos de early check-in y late check-out, límite de sobreventa, impuestos, series de comprobantes y tipo de cambio del día.

## Auditoría

**Auditoría** (`g` `a`) registra quién hizo qué y cuándo: ingresos, descuentos, anulaciones, cambios de tarifa, cierres de caja, permisos y accesos a datos personales. Nadie puede modificar ni borrar estos registros.

## Respaldos

- Cada cierre de día y cada día con el programador de tareas se guarda un respaldo comprimido, que se conserva 30 días.
- Para comprobar el último: `python manage.py backup_pms --verify`.
- Para restaurar en una base nueva: `python manage.py migrate` y luego `python manage.py loaddata <archivo>.json.gz`.

## Integraciones

| Integración | Variable | Valores |
| --- | --- | --- |
| Cerradura de tarjetas | `DOOR_LOCK` | `test`, `salto`, `none` |
| Central telefónica | `PBX`, `PBX_TOKEN`, `PBX_RATES` | `test` o `none`; la central envía cada llamada a `/integraciones/pbx/cdr/` |
| Channel manager | `CHANNEL_MANAGER` | `test`, `siteminder` |
| Pasarela de pagos | `PAYMENT_GATEWAY` | `test`, `culqi` |
| SUNAT | `SUNAT_MODE` | `simulator`, `production` |
