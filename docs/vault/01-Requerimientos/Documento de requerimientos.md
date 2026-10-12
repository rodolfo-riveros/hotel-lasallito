---
tags: [requerimientos, fuente]
---
# Requerimientos PMS Hotelero Cusco (Django)

Oct 12, 2026 · @Rodolfo Riveros  Mitma

## 1. Visión, alcance y objetivos

El sistema es un PMS (Property Management System) web en Django para hoteles de Cusco, con el nivel funcional de cadenas como Belmond o Sonesta Posadas del Inca: reservas, recepción, housekeeping, almacén, restaurante, facturación SUNAT, reportes y canales de venta, en español, inglés y portugués.

**Propósito de esta versión:** el sistema se usa para enseñar gestión hotelera y funciona igual que un PMS profesional de cadena. La única diferencia es que la facturación SUNAT (boletas, facturas, notas y consultas de RUC y DNI) es una simulación. Cada alumno o grupo puede trabajar en su propio hotel de práctica. El detalle está en las secciones 12 a 14.

**Objetivos**

- Que recepción haga check-in y check-out en menos de 2 minutos por huésped.
- Eliminar el overbooking sincronizando todos los canales de venta (Booking, Expedia, web propia, agencias).
- Emitir comprobantes electrónicos SUNAT válidos desde el mismo flujo de cobro.
- Dar al gerente un tablero con ocupación, ADR, RevPAR e ingresos en tiempo real.
- Controlar el almacén (alimentos, lencería, amenities, mantenimiento) con costos por consumo.

**Dentro del alcance**

- Gestión de una o varias propiedades (hotel, hostal, boutique).
- Operación diaria: front desk, housekeeping, F&B, almacén, compras, mantenimiento, caja.
- Motor de reservas web y channel manager.
- Facturación electrónica y reportes tributarios y gerenciales.

**Fuera del alcance (versión 1)**

- Contabilidad general completa y planillas (solo exportación a sistemas contables).
- Cerraduras inteligentes propias (solo integración posterior).
- App móvil nativa (se entrega web responsive/PWA).

## 2. Contexto de Cusco y Perú que el sistema debe resolver

Cusco recibe turistas de Norteamérica, Europa, Brasil, Argentina, Chile, Asia y Oceanía, con llegadas escalonadas por vuelo y por tren a Machu Picchu. Eso crea necesidades que un PMS genérico no cubre.

| Particularidad local | Qué exige al sistema |
| --- | --- |
| Turista extranjero | Registro con pasaporte, nacionalidad, tarjeta andina de migraciones (TAM) y fecha de ingreso al país |
| Exoneración de IGV | Venta a no domiciliados por alojamiento: IGV 0% si el huésped tiene condición de no domiciliado y su pasaporte registrado; el sistema debe validar y dejar rastro |
| Altura (3 399 msnm) | Servicios de oxígeno, té de coca y alerta de aclimatación al llegar; campos de alergias y condiciones médicas del huésped |
| Temporadas | Alta (mayo–setiembre, Inti Raymi en junio, Semana Santa, Fiestas Patrias) y baja (enero–marzo); tarifas y mínimos de estadía por fecha |
| Machu Picchu y trenes | Reserva de equipaje en custodia, desayunos temprano o para llevar, coordinación de traslados y tours |
| Multimoneda | Tarifas y cobros en soles (PEN) y dólares (USD), con tipo de cambio diario |
| Idiomas | Interfaz del personal en español; comunicaciones al huésped en español, inglés y portugués |
| Conectividad | Cortes de internet frecuentes: el front desk debe seguir operando |
| Normativa | Comprobantes electrónicos SUNAT, registro de huéspedes, ley de protección de datos personales (Ley 29733), libro de reclamaciones, DIRCETUR/MINCETUR |

## 3. Roles de usuario y permisos

El acceso se controla por rol y por propiedad; cada acción sensible (descuentos, anulaciones, cambios de tarifa) queda en un registro de auditoría con usuario, fecha, IP y valor anterior.

| Rol | Qué hace en el sistema | Restricciones clave |
| --- | --- | --- |
| Administrador del sistema | Configura propiedades, usuarios, impuestos, series SUNAT | Acceso total, sin operar caja |
| Gerente general | Reportes, tarifas, aprobaciones, auditoría | Aprueba descuentos y anulaciones |
| Recepcionista | Reservas, check-in/out, cobros, folio del huésped | No ve costos de compra ni márgenes |
| Jefe de recepción / Night Auditor | Cierre de día, corrección de folios, reportes de turno | Cierra el día contable |
| Reservas / Ventas | Cotizaciones, grupos, agencias, contratos | No cobra en caja |
| Housekeeping (gobernanta y mucamas) | Estado de habitaciones, tareas, objetos perdidos | Solo ve habitaciones asignadas |
| Mantenimiento | Órdenes de trabajo, bloqueo de habitaciones | Solo sus órdenes |
| Almacenero | Ingresos, salidas, inventarios, kardex | No emite comprobantes |
| Compras | Requisiciones, órdenes de compra, proveedores | Aprobación por monto |
| Restaurante / Bar (cajero, mozo, cocina) | Comandas, cuentas, cargo a habitación | Solo su punto de venta |
| Contador / Finanzas | Comprobantes, cuentas por cobrar y pagar, exportaciones | Solo lectura operativa |
| Huésped (portal web) | Ver reserva, pre-check-in, solicitar servicios | Solo sus datos |

- **RF-SEG-01:** roles personalizables con permisos por módulo y acción (ver, crear, editar, anular, aprobar, exportar).
- **RF-SEG-02:** un usuario puede tener acceso a varias propiedades con roles distintos en cada una.
- **RF-SEG-03:** inicio de sesión con doble factor opcional para gerencia y finanzas.

## 4. Requerimientos funcionales: núcleo operativo del hotel

### 4.1 Reservas

- **RF-RES-01:** crear reserva con huésped, fechas, tipo de habitación, número de adultos y niños, tarifa, canal de origen y observaciones.
- **RF-RES-02:** calendario de disponibilidad tipo "tape chart" (habitaciones en filas, días en columnas) con arrastrar y soltar para mover o extender estadías.
- **RF-RES-03:** estados de reserva: cotización, pendiente, confirmada, garantizada, check-in, check-out, no show, cancelada.
- **RF-RES-04:** reservas de grupo con bloqueo de habitaciones (rooming list), fecha límite de liberación y contrato.
- **RF-RES-05:** reservas de agencias y operadores con tarifa neta, comisión y crédito.
- **RF-RES-06:** política de cancelación configurable por tarifa (gratis hasta X días, penalidad de 1 noche, no reembolsable) con cálculo automático del cargo.
- **RF-RES-07:** depósito o garantía con tarjeta, transferencia o Yape/Plin, y registro de pagos parciales.
- **RF-RES-08:** lista de espera y sobreventa controlada con alerta al gerente.
- **RF-RES-09:** asignación de habitación automática o manual, con preferencias (piso, vista, cama, silencio).
- **RF-RES-10:** historial completo de cambios de cada reserva.
- **RF-RES-11:** correo de confirmación automático en el idioma del huésped, con PDF de la reserva.

### 4.2 Recepción: check-in, estadía y check-out

- **RF-REC-01:** llegadas y salidas del día en un panel único, con filtros por hora estimada de llegada y estado de la habitación.
- **RF-REC-02:** check-in rápido: buscar reserva, validar documento, asignar habitación, firmar ficha digital y entregar llave.
- **RF-REC-03:** ficha de registro del huésped con campos para extranjero: pasaporte, nacionalidad, fecha de ingreso al Perú, TAM, procedencia y destino.
- **RF-REC-04:** captura de documento con cámara o escáner, y validación de DNI contra RENIEC cuando el huésped es peruano.
- **RF-REC-05:** pre-check-in en línea: el huésped llena sus datos y sube su pasaporte antes de llegar.
- **RF-REC-06:** check-in de walk-in (sin reserva) en menos de 3 pasos.
- **RF-REC-07:** early check-in y late check-out con cargo automático configurable.
- **RF-REC-08:** cambio de habitación (upgrade, downgrade, reubicación) conservando el folio.
- **RF-REC-09:** folio del huésped: cargos de habitación, restaurante, bar, lavandería, minibar, tours, oxígeno y otros, con división de cuenta entre varias personas o empresas.
- **RF-REC-10:** check-out rápido con folio final, cobro, comprobante electrónico y encuesta de salida.
- **RF-REC-11:** custodia de equipaje con número de ticket y registro de entrada y salida.
- **RF-REC-12:** libro de novedades y mensajes entre turnos, y alertas de VIP, cumpleaños, alergias y solicitudes especiales.
- **RF-REC-13:** cierre de día (night audit) automático: cargo de habitaciones, no shows, cierre de caja, respaldo y reporte.
- **RF-REC-14:** pedido de despertador, wake-up call y registro de llamadas pendientes.

### 4.3 Habitaciones y tipos

- **RF-HAB-01:** catálogo de tipos de habitación (simple, doble, matrimonial, triple, suite, familiar) con fotos, descripción, capacidad, camas y comodidades en tres idiomas.
- **RF-HAB-02:** habitaciones individuales con piso, vista, ubicación, características (calefacción, oxígeno, balcón) y estado.
- **RF-HAB-03:** bloqueo de habitaciones por mantenimiento, remodelación o uso interno, con fechas y motivo.
- **RF-HAB-04:** habitaciones combinables (conectadas) para familias y grupos.
- **RF-HAB-05:** inventario de cada habitación (televisor, frigobar, bata, etc.) para revisión en housekeeping.

### 4.4 Housekeeping

- **RF-HK-01:** estados: limpia, sucia, en limpieza, inspeccionada, fuera de servicio, ocupada y vacía, con cambio desde el celular.
- **RF-HK-02:** asignación diaria de habitaciones por mucama con balance de carga y prioridad (salidas primero, llegadas tempranas, VIP).
- **RF-HK-03:** lista de tareas con checklist por tipo de limpieza (salida, estadía, profunda) y registro de tiempos.
- **RF-HK-04:** inspección de la gobernanta con aprobación o rechazo y fotos.
- **RF-HK-05:** control de minibar y reposición de amenities por habitación, que descuenta del almacén.
- **RF-HK-06:** objetos perdidos y encontrados con foto, fecha, lugar y entrega al dueño.
- **RF-HK-07:** lencería: entrada y salida a lavandería, conteo por tipo y stock por piso.
- **RF-HK-08:** aviso a recepción al terminar la limpieza para liberar la habitación.

### 4.5 Tarifas y precios

- **RF-TAR-01:** planes de tarifa: rack, corporativa, agencia, paquete, promoción, residente peruano, no reembolsable y estadía larga.
- **RF-TAR-02:** tarifas por temporada (alta, media, baja) y por fecha especial, con mínimo de noches y días de entrada o salida restringidos.
- **RF-TAR-03:** tarifas en PEN y USD con tipo de cambio diario editable, y redondeo configurable.
- **RF-TAR-04:** planes de alimentación: solo alojamiento, desayuno incluido, media pensión y pensión completa.
- **RF-TAR-05:** precio por ocupación (adulto adicional, niño, cama extra, cuna).
- **RF-TAR-06:** impuestos configurables: IGV 18%, servicio, impuesto municipal; exoneración automática al marcar huésped no domiciliado.
- **RF-TAR-07:** descuentos con tope por rol y aprobación del gerente.
- **RF-TAR-08:** precios dinámicos sugeridos según ocupación proyectada (fase 3).

## 5. Requerimientos funcionales: huéspedes, ventas, almacén y finanzas

### 5.1 Huéspedes y fidelización (CRM)

- **RF-HUE-01:** perfil único por huésped con documento, nacionalidad, idioma, contacto, preferencias, alergias, historial de estadías y gasto total.
- **RF-HUE-02:** detección de duplicados por documento, correo o teléfono, con fusión de perfiles.
- **RF-HUE-03:** etiquetas (VIP, recurrente, empresa, agencia) y lista negra con motivo.
- **RF-HUE-04:** programa de fidelidad con puntos o niveles y beneficios configurables.
- **RF-HUE-05:** encuestas de satisfacción post-estadía y registro de quejas con seguimiento.
- **RF-HUE-06:** consentimiento de datos personales y derecho de acceso y eliminación (Ley 29733).
- **RF-HUE-07:** cuentas de empresas y agencias con RUC, crédito, contactos y convenios.

### 5.2 Restaurante, bar y servicios (POS)

- **RF-POS-01:** puntos de venta configurables: restaurante, bar, room service, tienda, spa, tours.
- **RF-POS-02:** mapa de mesas, comandas por mozo, envío a cocina o barra, división de cuenta y propinas.
- **RF-POS-03:** carta digital en español, inglés y portugués con alérgenos y fotos.
- **RF-POS-04:** cargo a habitación con firma digital o validación de recepción.
- **RF-POS-05:** recetas e insumos por plato: cada venta descuenta del almacén en gramos, litros o unidades.
- **RF-POS-06:** desayuno incluido: control de huéspedes con desayuno y desayuno para llevar hacia Machu Picchu.
- **RF-POS-07:** servicios adicionales como cargos: lavandería, oxígeno, traslados, tours, spa, minibar.
- **RF-POS-08:** impresión de comandas en cocina y de precuenta, con opción de pantalla de cocina (KDS).

### 5.3 Almacén e inventario

- **RF-ALM-01:** múltiples almacenes (general, cocina, bar, housekeeping, mantenimiento) con stock por ubicación.
- **RF-ALM-02:** catálogo de artículos con código, categoría, unidad de medida, equivalencias (caja y unidad), stock mínimo y máximo.
- **RF-ALM-03:** ingresos por compra con guía y factura, salidas por requisición, transferencias entre almacenes y ajustes con motivo.
- **RF-ALM-04:** kardex valorizado con método de costo promedio ponderado.
- **RF-ALM-05:** control de lotes y fechas de vencimiento para alimentos, con alerta previa.
- **RF-ALM-06:** inventario físico por conteo (también desde el celular) y reporte de diferencias.
- **RF-ALM-07:** alertas de stock mínimo y sugerencia de pedido.
- **RF-ALM-08:** mermas y bajas con aprobación y registro fotográfico.
- **RF-ALM-09:** activos fijos: mobiliario, equipos y su ubicación por habitación o área.
- **RF-ALM-10:** lencería y menaje como inventario rotativo con conteo de bajas.

### 5.4 Compras y proveedores

- **RF-COM-01:** requisición interna por área, con aprobación por monto.
- **RF-COM-02:** cotizaciones comparativas a varios proveedores y orden de compra con PDF.
- **RF-COM-03:** recepción parcial o total de mercadería contra la orden de compra.
- **RF-COM-04:** registro de proveedores con RUC (validado con SUNAT), condiciones de pago y evaluación.
- **RF-COM-05:** cuentas por pagar con vencimientos y exportación a contabilidad.

### 5.5 Mantenimiento

- **RF-MAN-01:** órdenes de trabajo creadas por housekeeping, recepción o huésped, con prioridad, responsable y estado.
- **RF-MAN-02:** mantenimiento preventivo programado (calentadores, calderos, ascensor, extintores) con calendario.
- **RF-MAN-03:** bloqueo automático de la habitación mientras la orden esté abierta.
- **RF-MAN-04:** historial de reparaciones y costo por habitación y por equipo.

### 5.6 Facturación electrónica SUNAT

- **RF-FAC-01:** emisión de boleta, factura, nota de crédito y nota de débito, con series por sede y punto de venta.
- **RF-FAC-02:** envío a SUNAT mediante un OSE o PSE (por ejemplo Nubefact, Efact o similar) con reintento automático si hay falla.
- **RF-FAC-03:** representación impresa y PDF en español e inglés, con envío por correo al huésped.
- **RF-FAC-04:** exoneración de IGV a no domiciliados con leyenda legal, registro del documento de identidad y fecha de ingreso al país.
- **RF-FAC-05:** facturación a empresas con validación de RUC y razón social.
- **RF-FAC-06:** facturación diferida (agrupada por periodo o por agencia) y adelantos de reserva.
- **RF-FAC-07:** comprobantes en soles o dólares con tipo de cambio SUNAT del día.
- **RF-FAC-08:** libro de ventas y registros electrónicos exportables para el contador (PLE).
- **RF-FAC-09:** guías de remisión para traslado de bienes cuando corresponda.
- **RF-FAC-10:** anulación y baja de comprobantes con control de plazos y permisos.

### 5.7 Caja y pagos

- **RF-CAJ-01:** apertura y cierre de caja por turno y por usuario, con arqueo y diferencias.
- **RF-CAJ-02:** medios de pago: efectivo PEN y USD, tarjeta (POS físico), transferencia, Yape y Plin, enlace de pago y cuenta corriente.
- **RF-CAJ-03:** pagos parciales, adelantos, devoluciones y propinas.
- **RF-CAJ-04:** conciliación diaria por medio de pago y caja chica con rendición de gastos.
- **RF-CAJ-05:** cuentas por cobrar a empresas y agencias con antigüedad de saldos y estados de cuenta.

### 5.8 Reportes y tablero gerencial

- **RF-REP-01:** indicadores en tiempo real: ocupación, ADR (tarifa promedio), RevPAR, ingresos por habitación y por área, llegadas y salidas.
- **RF-REP-02:** reportes: ocupación por periodo y tipo, ingresos por canal y agencia, procedencia de huéspedes por país, estadía promedio, cancelaciones y no shows.
- **RF-REP-03:** reportes operativos: reservas del día, in-house, rooming list, estado de habitaciones, consumo de almacén y costo de alimentos.
- **RF-REP-04:** reporte de pronóstico (forecast) de ocupación a 30, 60 y 90 días con comparación contra el año anterior.
- **RF-REP-05:** reportes para MINCETUR y DIRCETUR (estadística de arribos y pernoctaciones) exportables.
- **RF-REP-06:** exportación a PDF, Excel y CSV, y envío programado por correo al gerente.

## 6. Requerimientos funcionales: ventas, canales y experiencia del huésped

### 6.1 Channel manager

- **RF-CHA-01:** sincronización bidireccional de disponibilidad, tarifas y restricciones con Booking.com, Expedia, Airbnb y agencias en línea, mediante un channel manager externo (por ejemplo SiteMinder, Cloudbeds o similar) o conexión directa.
- **RF-CHA-02:** las reservas de cada canal entran al sistema automáticamente y bajan la disponibilidad en todos los demás.
- **RF-CHA-03:** mapeo de tipos de habitación y planes de tarifa por canal, con comisión de cada uno.
- **RF-CHA-04:** panel de errores de sincronización con reintento y alerta al gerente.

### 6.2 Motor de reservas web (booking engine)

- **RF-WEB-01:** búsqueda por fechas y ocupantes con disponibilidad y precio en tiempo real, adaptado a celular.
- **RF-WEB-02:** sitio en español, inglés y portugués, con precio en PEN o USD a elección.
- **RF-WEB-03:** pago en línea con tarjeta (Izipay, Niubiz o Culqi) y opción de pagar en el hotel.
- **RF-WEB-04:** códigos promocionales, venta adicional (desayuno, traslado aeropuerto, tour) y reserva de grupos por solicitud.
- **RF-WEB-05:** reserva confirmada por correo y WhatsApp, con enlace de pre-check-in.
- **RF-WEB-06:** SEO básico y datos estructurados de hotel para buscadores.

### 6.3 Tours, traslados y servicios externos

- **RF-TUR-01:** catálogo de servicios: city tour, Valle Sagrado, Machu Picchu, Montaña de Colores, traslado aeropuerto y estación de tren.
- **RF-TUR-02:** venta de servicios desde el folio con precio, costo y operador proveedor.
- **RF-TUR-03:** agenda diaria de recojos con hora, punto, pasajeros y operador, y envío al proveedor.
- **RF-TUR-04:** registro de tren e ingreso a Machu Picchu del huésped para coordinar desayuno temprano y equipaje.
- **RF-TUR-05:** liquidación y comisiones por servicio vendido.

### 6.4 Multi-propiedad

- **RF-MUL-01:** una sola instalación con varias propiedades, cada una con su RUC, series de comprobantes, tarifas, almacenes y usuarios.
- **RF-MUL-02:** vista consolidada para la gerencia y reportes comparativos por propiedad.
- **RF-MUL-03:** huéspedes y fidelidad compartidos entre propiedades del mismo grupo.

### 6.5 Comunicaciones

- **RF-COMU-01:** plantillas de correo y WhatsApp en tres idiomas: confirmación, recordatorio, bienvenida, agradecimiento y encuesta.
- **RF-COMU-02:** mensajes automáticos por evento (reserva, 48 horas antes de la llegada, check-out) con opción de apagarlos.
- **RF-COMU-03:** bandeja de mensajes con el huésped dentro de la reserva.
- **RF-COMU-04:** notificaciones internas al personal (nueva reserva, limpieza lista, orden de mantenimiento).

### 6.6 Portal del huésped

- **RF-POR-01:** enlace único por reserva para ver datos, completar pre-check-in, firmar la ficha y pagar el saldo.
- **RF-POR-02:** solicitar servicios (toallas extra, oxígeno, despertador, traslado) y ver el estado de la solicitud.
- **RF-POR-03:** consultar el folio de consumos y descargar comprobantes.

## 7. Requerimientos no funcionales

### 7.1 Rendimiento

- **RNF-REN-01:** las pantallas de recepción cargan en menos de 2 segundos con conexión normal y las búsquedas de reserva responden en menos de 1 segundo.
- **RNF-REN-02:** el sistema soporta 50 usuarios concurrentes por propiedad y 100 000 reservas históricas sin degradarse.
- **RNF-REN-03:** la sincronización de disponibilidad con canales ocurre en menos de 60 segundos tras un cambio.
- **RNF-REN-04:** los reportes pesados se generan en segundo plano (Celery) y avisan al terminar.

### 7.2 Disponibilidad y continuidad

- **RNF-DIS-01:** disponibilidad objetivo de 99,5% mensual, con mantenimiento fuera del horario pico.
- **RNF-DIS-02:** respaldos automáticos diarios de la base de datos, retenidos 30 días, con copia fuera del servidor y prueba de restauración mensual.
- **RNF-DIS-03:** modo de contingencia para recepción: lista de llegadas, huéspedes in-house y habitaciones disponibles descargables en PDF o Excel si falla internet.
- **RNF-DIS-04:** si falla SUNAT o el OSE, los comprobantes se encolan y se envían al recuperarse la conexión, sin perder numeración.
- **RNF-DIS-05:** recuperación ante desastres con objetivo de 4 horas (RTO) y pérdida máxima de 1 hora de datos (RPO).

### 7.3 Seguridad y privacidad

- **RNF-SEG-01:** HTTPS obligatorio, contraseñas con hash seguro (Argon2), bloqueo tras intentos fallidos y cierre de sesión por inactividad.
- **RNF-SEG-02:** control de acceso por rol en cada vista y consulta, con pruebas automáticas de permisos.
- **RNF-SEG-03:** auditoría inmutable de acciones críticas: anulaciones, descuentos, cambios de tarifa, cierres de caja y accesos a datos de huéspedes.
- **RNF-SEG-04:** datos de pasaporte y contacto cifrados en reposo; datos de tarjeta nunca almacenados en el sistema (se usa el tokenizado de la pasarela, cumpliendo PCI DSS por delegación).
- **RNF-SEG-05:** protección contra las vulnerabilidades más comunes (OWASP Top 10): inyección SQL, XSS, CSRF, subida de archivos maliciosos.
- **RNF-SEG-06:** cumplimiento de la Ley 29733 de protección de datos personales: consentimiento, finalidad, conservación limitada y derecho de eliminación.
- **RNF-SEG-07:** secretos y llaves en variables de entorno, nunca en el código.

### 7.4 Experiencia de usuario y diseño visual

- **RNF-UX-01:** diseño limpio y de nivel hotelero premium, con identidad configurable por propiedad (logo, colores, tipografía) y modo oscuro opcional.
- **RNF-UX-02:** interfaz responsive: recepción en computadora, housekeeping y mantenimiento en celular o tablet, portal del huésped en celular primero.
- **RNF-UX-03:** flujos de recepción operables con teclado (atajos) y con máximo 3 clics para las tareas frecuentes.
- **RNF-UX-04:** colores de estado consistentes en todo el sistema (habitación libre, ocupada, sucia, bloqueada; reserva confirmada o pendiente) y apto para daltonismo.
- **RNF-UX-05:** mensajes de error claros, confirmaciones antes de acciones destructivas y deshacer cuando sea posible.
- **RNF-UX-06:** accesibilidad mínima WCAG 2.1 nivel AA en el portal del huésped.
- **RNF-UX-07:** capacitación mínima: un recepcionista nuevo opera tras 2 horas de entrenamiento, apoyado por ayudas contextuales.

### 7.5 Idiomas y localización

- **RNF-I18N-01:** interfaz del personal en español; portal, correos, comprobantes y carta en español, inglés y portugués, con arquitectura lista para agregar más idiomas.
- **RNF-I18N-02:** zona horaria America/Lima, formato de fecha local y soporte de PEN y USD con separadores correctos.
- **RNF-I18N-03:** nombres de huéspedes con caracteres especiales (tildes, ñ, alfabetos no latinos) sin errores.

### 7.6 Mantenibilidad y calidad

- **RNF-MAN-01:** código organizado por apps de Django con responsabilidades claras, tipado y estándares (PEP 8, Black, Ruff).
- **RNF-MAN-02:** cobertura de pruebas automáticas mínima de 80% en reglas de negocio (tarifas, disponibilidad, impuestos, folio, facturación).
- **RNF-MAN-03:** migraciones versionadas, datos de ejemplo (fixtures) y documentación técnica y de usuario.
- **RNF-MAN-04:** despliegue reproducible con Docker, integración continua y entornos de desarrollo, pruebas y producción separados.
- **RNF-MAN-05:** registros (logs) estructurados y monitoreo de errores (por ejemplo Sentry).

### 7.7 Integridad de datos

- **RNF-INT-01:** transacciones atómicas en reservas, pagos y comprobantes para evitar dobles reservas y numeración duplicada.
- **RNF-INT-02:** bloqueo concurrente al asignar habitaciones, de modo que dos recepcionistas no vendan la misma.
- **RNF-INT-03:** borrado lógico (nunca físico) de reservas, huéspedes y comprobantes.

## 8. Arquitectura Django propuesta y modelo de datos

Se propone un monolito modular en Django: una sola base de código con apps independientes, más simple de mantener que microservicios y suficiente para este volumen.

### 8.1 Stack recomendado

- **Backend:** Python 3.12, Django 5, Django REST Framework para la API.
- **Base de datos:** PostgreSQL alojada en Supabase (sección 13), con restricciones de exclusión para evitar solapamiento de reservas por habitación.
- **Tareas en segundo plano:** Celery con Redis (sincronización de canales, correos, reportes, cierre de día).
- **Frontend:** plantillas Django con HTMX y Alpine.js, Tailwind CSS; así se evita una SPA compleja y se mantiene un diseño pulido. Calendario de disponibilidad con un componente de agenda dedicado.
- **Tiempo real:** Django Channels o sondeo HTMX para estados de habitaciones y comandas.
- **Archivos:** Supabase Storage (compatible con S3) para pasaportes, fotos y PDFs.
- **Despliegue:** Docker, Nginx, Gunicorn, HTTPS, respaldos automáticos.
- **Calidad:** pytest, factory\_boy, Ruff, pre-commit, GitHub Actions.

### 8.2 Apps de Django

| App | Responsabilidad | Modelos principales |
| --- | --- | --- |
| `core` | Propiedades, configuración, auditoría, monedas, impuestos | Property, Currency, ExchangeRate, TaxRule, AuditLog |
| `accounts` | Usuarios, roles y permisos por propiedad | User, Role, PropertyAccess |
| `guests` | Huéspedes, empresas, agencias, fidelidad | Guest, Company, Agency, LoyaltyAccount, Consent |
| `rooms` | Tipos de habitación, habitaciones, bloqueos | RoomType, Room, RoomBlock, RoomFeature |
| `rates` | Planes de tarifa, temporadas, restricciones | RatePlan, Season, RateRule, Promotion, CancellationPolicy |
| `reservations` | Reservas, grupos, disponibilidad, estadías | Reservation, ReservationRoom, GroupBlock, Stay |
| `frontdesk` | Check-in/out, ficha, equipaje, novedades | CheckIn, RegistrationCard, LuggageTicket, ShiftLog |
| `folio` | Cuenta del huésped, cargos, pagos, caja | Folio, Charge, Payment, CashRegister, CashSession |
| `billing` | Comprobantes SUNAT, series, notas | Invoice, InvoiceLine, Series, SunatResponse |
| `housekeeping` | Limpieza, inspección, lencería, objetos perdidos | CleaningTask, Inspection, LostItem, LinenMovement |
| `maintenance` | Órdenes de trabajo y preventivo | WorkOrder, PreventivePlan, Asset |
| `pos` | Restaurante, bar, room service, recetas | Outlet, Table, Order, OrderItem, MenuItem, Recipe |
| `inventory` | Almacenes, artículos, kardex, lotes | Warehouse, Item, StockMovement, Lot, StockCount |
| `purchasing` | Requisiciones, órdenes de compra, proveedores | Supplier, Requisition, PurchaseOrder, GoodsReceipt |
| `channels` | Channel manager, sincronización, mapeos | Channel, ChannelMapping, SyncLog |
| `booking_engine` | Sitio de reservas y pago en línea | Quote, OnlinePayment |
| `tours` | Servicios externos, traslados, operadores | Service, ServiceBooking, Operator |
| `comms` | Plantillas, mensajes, notificaciones | Template, Message, Notification |
| `reports` | Tableros, reportes, exportaciones | ReportDefinition, ScheduledReport |

### 8.3 Reglas de modelo que no deben romperse

- Una habitación no puede tener dos estadías que se solapen en fechas (restricción en base de datos, no solo en código).
- Todo cargo pertenece a un folio y todo comprobante a uno o más cargos; los montos se guardan en `Decimal`, nunca en flotantes.
- Reservas, huéspedes y comprobantes usan borrado lógico y registran creador, fecha y última modificación.
- La numeración de comprobantes es correlativa por serie y se asigna dentro de una transacción.
- Cada registro operativo lleva la propiedad (`property`) para aislar datos entre hoteles del grupo.

## 9. Integraciones externas

Todas las integraciones se construyen como en un PMS real, detrás de una interfaz propia (patrón adaptador). La única parte simulada en esta versión es la que depende de SUNAT: comprobantes, consultas de RUC y DNI, y tipo de cambio (sección 12).

| Integración | Estado en esta versión | Proveedor |
| --- | --- | --- |
| Facturación electrónica SUNAT | Simulada | OSE o PSE (Nubefact, Efact u otro) cuando se pase a producción |
| Consulta RUC y DNI | Simulada con base local de datos ficticios | API de consultas SUNAT y RENIEC |
| Tipo de cambio | Tabla editable a mano | Tipo de cambio SUNAT automático |
| Pasarela de pagos | Real, probada en el entorno de pruebas del proveedor | Izipay, Niubiz o Culqi |
| Yape y Plin | Registro del cobro en recepción, como en un hotel real | API del proveedor si la ofrece |
| Correo transaccional | Real | Amazon SES, Brevo u otro |
| WhatsApp | Real, con plantillas | WhatsApp Business API |
| Channel manager (Booking, Expedia, Airbnb) | Real mediante conector, probado en entorno de pruebas | SiteMinder, Cloudbeds u otro |
| Cerraduras electrónicas y PBX | Fase 3, opcional | Según marca del hotel |
| Exportación contable | Excel y PLE con formato real, marcados como ejemplo | Contador del hotel |

## 10. Fases de desarrollo

El sistema se construye en cuatro fases, cada una utilizable por sí sola; la fase 1 ya permite operar un hotel pequeño de punta a punta. Los tiempos son estimados de referencia para un desarrollador con Claude Code y se ajustan al avanzar.

| Fase | Alcance | Se da por terminada cuando | Estimado |
| --- | --- | --- | --- |
| 0. Base | Proyecto Django, Docker, PostgreSQL, usuarios y roles, propiedad, auditoría, diseño base (Tailwind, componentes), idiomas | Se inicia sesión por rol y el diseño base está aprobado | 1–2 semanas |
| 1. MVP operativo | Habitaciones y tarifas, reservas con calendario, check-in/out, folio, caja, housekeeping básico, huéspedes, facturación SUNAT vía OSE, reportes esenciales | Un hotel completa un día real: reserva, check-in, cargos, check-out con boleta o factura válida y cierre de caja | 6–8 semanas |
| 2. Operación completa | Almacén y kardex, compras, POS de restaurante y bar con recetas, mantenimiento, portal del huésped, pre-check-in, comunicaciones, pagos en línea | Consumos de cocina descuentan stock y el huésped hace pre-check-in desde su celular | 6–8 semanas |
| 3. Ventas y crecimiento | Channel manager, motor de reservas web, tours y traslados, multi-propiedad, fidelidad, pronóstico y precios sugeridos | Una reserva de Booking baja la disponibilidad en todos los canales sin intervención | 6–8 semanas |
| 4. Pulido | Integraciones opcionales (cerraduras, PBX), PWA, optimización, pruebas de carga, manual de usuario | Prueba de carga cumplida y capacitación del personal completada | 2–3 semanas |

## 11. Criterios de aceptación y prompt inicial para Claude Code

### 11.1 Criterios de aceptación del MVP (fase 1)

- [ ] Dos recepcionistas no pueden vender la misma habitación para las mismas fechas, ni siquiera al mismo tiempo.
- [ ] Se completa el flujo reserva, check-in, cargos, check-out, boleta o factura y cierre de caja sin salir del sistema.
- [ ] Un huésped extranjero con pasaporte genera comprobante con IGV exonerado y la leyenda correspondiente.
- [ ] Los cambios de tarifa, descuentos y anulaciones quedan en auditoría con usuario y hora.
- [ ] El tablero muestra ocupación, ADR y RevPAR correctos frente a un cálculo manual de prueba.
- [ ] Todas las pantallas funcionan en celular y las de recepción se operan con teclado.
- [ ] Los correos de confirmación salen en el idioma del huésped.
- [ ] Las pruebas automáticas de disponibilidad, tarifas, impuestos y numeración pasan al 100%.

### 11.2 Decisiones por confirmar antes de programar

- Cuántos alumnos o grupos usarán el sistema a la vez, para dimensionar la base de datos.
- Si la primera versión es para un solo hotel o ya para varias propiedades.
- Si la pasarela de pagos y el channel manager tendrán cuentas reales desde el inicio o solo entorno de pruebas, y con qué proveedor.
- En el modo aula, cada alumno o grupo tiene su propia propiedad.
- Si hay restaurante propio desde el inicio, para priorizar el POS.

### 11.3 Prompt inicial para pegar en Claude Code

```markdown
Actúa como arquitecto y desarrollador senior de Django. Vamos a construir un PMS hotelero (sistema de gestión de hoteles) para hoteles de Cusco, Perú, con turistas extranjeros, facturación electrónica SUNAT, moneda PEN/USD y textos en español, inglés y portugués.

Trabaja con el documento de requerimientos adjunto como fuente de verdad (RF = funcionales, RNF = no funcionales).

Reglas de trabajo:
1. Antes de programar, resume tu plan de la fase 0 y espera mi confirmación.
2. Usa monolito modular Django 5 + PostgreSQL en Supabase + Celery/Redis + HTMX + Alpine.js + Tailwind. Una app por módulo, como en la sección 8.2.
3. Cada requerimiento que implementes lleva su prueba automática y se cita por su código (por ejemplo RF-RES-02).
4. Montos en Decimal, borrado lógico, auditoría en acciones críticas, transacciones en reservas, pagos y comprobantes.
5. Solo la facturación SUNAT y sus consultas se simulan (sección 12); todo lo demás funciona como un PMS real. Integraciones detrás de adaptadores.
6. Diseño visual premium y consistente: componentes reutilizables, colores de estado definidos una sola vez, responsive.
7. Trabaja por fases (sección 10); no avances a la siguiente sin mi aprobación.
8. Mantén CLAUDE.md y documenta todo lo que hagas en la bóveda de Obsidian (sección 14).

Empieza por la fase 0.
```

## 12. Simulación de SUNAT y modo aula

El sistema funciona como un PMS hotelero real de punta a punta: reservas, recepción, housekeeping, almacén, restaurante, caja, correos, canales y reportes. Lo único que cambia es que nada se envía a SUNAT ni a un OSE: esa parte la reemplaza un simulador. Una variable de configuración (`SUNAT_MODE=simulator`) lo activa; cuando se quiera facturar de verdad, se cambia a `production` y se conecta un OSE o PSE sin tocar el resto del sistema.

| Qué se simula | Cómo se comporta |
| --- | --- |
| Emisión de boleta, factura, nota de crédito y nota de débito | Mismo flujo y mismas validaciones que en la realidad: serie y correlativo por sede, RUC de 11 dígitos, DNI en boletas mayores a S/ 700, exoneración de IGV a no domiciliados. El PDF lleva marca de agua "SIMULACIÓN, SIN VALOR TRIBUTARIO" |
| Respuesta de SUNAT | Aceptación ficticia (constancia simulada); el docente puede activar rechazos o fallas de conexión para practicar |
| Anulación y baja de comprobantes, resumen diario de boletas | Se procesan con el mismo flujo y quedan aceptados de forma simulada |
| Consulta de RUC y DNI | Base local de empresas y personas inventadas; nunca datos reales |
| Tipo de cambio SUNAT | El docente o administrador lo edita a mano |
| Libros electrónicos (PLE) | Archivos con formato real, marcados como ejemplo |

**Funciones propias del modo aula**

- **RF-SIM-01:** hotel de ejemplo de Cusco con habitaciones, tarifas, huéspedes, proveedores y almacén ya cargados, y botón para restablecer los datos.
- **RF-SIM-02:** cada alumno o grupo trabaja en su propia propiedad aislada; el docente ve todas (se aprovecha el módulo multi-propiedad, que pasa a la fase 1).
- **RF-SIM-03:** escenarios de práctica con guía paso a paso: grupo de turistas con llegada tardía, overbooking, cambio de habitación, nota de crédito, cierre de caja con diferencia.
- **RF-SIM-04:** generador de eventos para el docente: llegan walk-ins, una agencia cancela, falla SUNAT, se acaba el stock de un insumo.
- **RF-SIM-05:** panel del docente con avance por alumno, historial de acciones y un resumen de errores cometidos.
- **RF-SIM-06:** la leyenda "SIMULACIÓN, SIN VALOR TRIBUTARIO" aparece en cada comprobante y en las pantallas de facturación; el resto del sistema se ve igual que uno real.
- **RF-SIM-07:** se recomienda usar datos ficticios de huéspedes en clase; no cargar pasaportes ni documentos reales de personas.

**Todo lo demás funciona como en un sistema real**

- Los correos y mensajes se envían de verdad, y los cobros y cierres de caja siguen las reglas de la sección 5.7.
- Pasarela de pagos y channel manager se construyen con su adaptador real y se prueban en el entorno de pruebas del proveedor; falta confirmar si tendrán cuentas reales (sección 11.2).
- Los requerimientos de las secciones 5.6 (facturación) y 5.7 (caja) se cumplen contra el simulador de SUNAT; el resto de requerimientos se implementa completo.

## 13. Base de datos en Supabase

Sí es posible: Supabase es PostgreSQL administrado, y Django se conecta a él como a cualquier base PostgreSQL. Django sigue creando y versionando las tablas con sus propias migraciones.

- **RF-BD-01:** la conexión se configura con una variable de entorno (`DATABASE_URL`) en un archivo `.env`; la contraseña nunca se sube al repositorio.
- **RF-BD-02:** se usa el pooler de Supabase en modo sesión (puerto 5432), que funciona bien con Django; si se usa el modo transacción (puerto 6543) hay que desactivar los cursores del lado del servidor.
- **RF-BD-03:** se habilita la extensión `btree_gist` para la restricción que impide reservas solapadas en la misma habitación.
- **RF-BD-04:** se activa RLS (seguridad por filas) en todas las tablas, sin políticas, para que nadie pueda leerlas por la API pública de Supabase; Django entra con su rol de servidor y no se ve afectado.
- **RF-BD-05:** el inicio de sesión sigue siendo el de Django (usuarios y roles propios); no se usa Supabase Auth en esta versión.
- **RF-BD-06:** las fotos y documentos de práctica se guardan en Supabase Storage.
- **RF-BD-07:** un proyecto Supabase de desarrollo y otro de producción o aula, con respaldos automáticos activados.

Un proyecto del plan gratuito de Supabase se pausa tras un tiempo sin actividad, así que para uso real en clase conviene revisar los límites del plan vigente antes de empezar.

## 14. Bitácora del proyecto en Obsidian

Claude Code deja constancia de todo lo que hace en una bóveda (vault) de Obsidian: una carpeta `docs/vault/` dentro del proyecto, con notas en Markdown que se abren en Obsidian y se versionan con Git junto al código. Obsidian no necesita plugins para esto.

| Carpeta | Contenido |
| --- | --- |
| `00-Inicio` | Índice del proyecto, estado actual y mapa de notas |
| `01-Requerimientos` | Una nota por módulo con sus RF y RNF como casillas que se marcan al implementarlos |
| `02-Decisiones` | Una nota por decisión técnica: contexto, opciones, decisión y motivo |
| `03-Bitacora` | Una nota por día de trabajo |
| `04-Modelo-de-datos` | Una nota por app de Django con sus modelos y relaciones |
| `05-Pendientes` | Errores conocidos, ideas y tareas siguientes |
| `06-Plantillas` | Plantillas de nota diaria, decisión y módulo |

- **RF-OBS-01:** al terminar cada sesión de trabajo, Claude Code crea o actualiza la nota del día en `03-Bitacora` con fecha, qué se hizo, archivos tocados, decisiones tomadas y qué sigue.
- **RF-OBS-02:** al implementar un requerimiento, marca su casilla en la nota del módulo y cita su código (por ejemplo RF-RES-02).
- **RF-OBS-03:** cada decisión técnica importante genera una nota en `02-Decisiones`.
- **RF-OBS-04:** las notas usan enlaces `[[así]]` entre sí, y un encabezado con fase, estado y etiquetas.
- **RF-OBS-05:** el modelo de datos se documenta en `04-Modelo-de-datos` cada vez que cambia una migración.
- **RF-OBS-06:** la bóveda se confirma en Git en el mismo commit que el código al que se refiere.

Plantilla de la nota diaria:

```markdown
---
fecha: 2026-10-12
fase: 1
tags: [bitacora]
---
# Bitácora 2026-10-12

## Qué se hizo
- 

## Requerimientos avanzados
- [[Reservas]]: RF-RES-01, RF-RES-02

## Decisiones
- [[Decisión - Supabase como base de datos]]

## Pendientes
- 
```
