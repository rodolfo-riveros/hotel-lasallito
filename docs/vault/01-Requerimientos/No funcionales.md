---
fase: 0-4
estado: en curso
tags: [requerimientos, no-funcionales]
---
# Requerimientos no funcionales

Fuente: [[Documento de requerimientos]] sección 7.

## Rendimiento

- [ ] **RNF-REN-01** las pantallas de recepción cargan en menos de 2 segundos con conexión normal y las búsquedas de reserva responden en menos de 1 segundo.
- [ ] **RNF-REN-02** el sistema soporta 50 usuarios concurrentes por propiedad y 100 000 reservas históricas sin degradarse.
- [ ] **RNF-REN-03** la sincronización de disponibilidad con canales ocurre en menos de 60 segundos tras un cambio.
- [ ] **RNF-REN-04** los reportes pesados se generan en segundo plano (Celery) y avisan al terminar.

## Disponibilidad

- [ ] **RNF-DIS-01** disponibilidad objetivo de 99,5% mensual, con mantenimiento fuera del horario pico.
- [ ] **RNF-DIS-02** respaldos automáticos diarios de la base de datos, retenidos 30 días, con copia fuera del servidor y prueba de restauración mensual.
- [x] **RNF-DIS-03** modo de contingencia para recepción: lista de llegadas, huéspedes in-house y habitaciones disponibles descargables en PDF o Excel si falla internet. ✅ fase 1
- [x] **RNF-DIS-04** si falla SUNAT o el OSE, los comprobantes se encolan y se envían al recuperarse la conexión, sin perder numeración. ✅ fase 1
- [ ] **RNF-DIS-05** recuperación ante desastres con objetivo de 4 horas (RTO) y pérdida máxima de 1 hora de datos (RPO).

## Seguridad

- [ ] **RNF-SEG-01** HTTPS obligatorio, contraseñas con hash seguro (Argon2), bloqueo tras intentos fallidos y cierre de sesión por inactividad. — 🟡 parcial: Argon2, bloqueo, inactividad y HTTPS en prod; falta probar despliegue
- [x] **RNF-SEG-02** control de acceso por rol en cada vista y consulta, con pruebas automáticas de permisos. ✅ fase 0
- [x] **RNF-SEG-03** auditoría inmutable de acciones críticas: anulaciones, descuentos, cambios de tarifa, cierres de caja y accesos a datos de huéspedes. ✅ fase 0
- [x] **RNF-SEG-04** datos de pasaporte y contacto cifrados en reposo; datos de tarjeta nunca almacenados en el sistema (se usa el tokenizado de la pasarela, cumpliendo PCI DSS por delegación). ✅ fase 1
- [x] **RNF-SEG-05** protección contra las vulnerabilidades más comunes (OWASP Top 10): inyección SQL, XSS, CSRF, subida de archivos maliciosos. ✅ fase 1
- [ ] **RNF-SEG-06** cumplimiento de la Ley 29733 de protección de datos personales: consentimiento, finalidad, conservación limitada y derecho de eliminación.
- [x] **RNF-SEG-07** secretos y llaves en variables de entorno, nunca en el código. ✅ fase 0

## Experiencia de usuario

- [x] **RNF-UX-01** diseño limpio y de nivel hotelero premium, con identidad configurable por propiedad (logo, colores, tipografía) y modo oscuro opcional. ✅ fase 1
- [x] **RNF-UX-02** interfaz responsive: recepción en computadora, housekeeping y mantenimiento en celular o tablet, portal del huésped en celular primero. ✅ fase 1
- [x] **RNF-UX-03** flujos de recepción operables con teclado (atajos) y con máximo 3 clics para las tareas frecuentes. ✅ fase 1
- [x] **RNF-UX-04** colores de estado consistentes en todo el sistema (habitación libre, ocupada, sucia, bloqueada; reserva confirmada o pendiente) y apto para daltonismo. ✅ fase 0
- [x] **RNF-UX-05** mensajes de error claros, confirmaciones antes de acciones destructivas y deshacer cuando sea posible. ✅ fase 1
- [ ] **RNF-UX-06** accesibilidad mínima WCAG 2.1 nivel AA en el portal del huésped.
- [ ] **RNF-UX-07** capacitación mínima: un recepcionista nuevo opera tras 2 horas de entrenamiento, apoyado por ayudas contextuales.

## Idiomas

- [ ] **RNF-I18N-01** interfaz del personal en español; portal, correos, comprobantes y carta en español, inglés y portugués, con arquitectura lista para agregar más idiomas. — 🟡 parcial: plantillas, carta y PDF en 3 idiomas; traducción de la interfaz del portal en la fase 2
- [x] **RNF-I18N-02** zona horaria America/Lima, formato de fecha local y soporte de PEN y USD con separadores correctos. ✅ fase 0
- [x] **RNF-I18N-03** nombres de huéspedes con caracteres especiales (tildes, ñ, alfabetos no latinos) sin errores. ✅ fase 1

## Mantenibilidad

- [x] **RNF-MAN-01** código organizado por apps de Django con responsabilidades claras, tipado y estándares (PEP 8, Black, Ruff). ✅ fase 0
- [ ] **RNF-MAN-02** cobertura de pruebas automáticas mínima de 80% en reglas de negocio (tarifas, disponibilidad, impuestos, folio, facturación). — 🟡 parcial: 129 pruebas de reglas de negocio; falta medir cobertura
- [ ] **RNF-MAN-03** migraciones versionadas, datos de ejemplo (fixtures) y documentación técnica y de usuario. — 🟡 parcial: migraciones, datos de ejemplo y README; falta manual de usuario
- [ ] **RNF-MAN-04** despliegue reproducible con Docker, integración continua y entornos de desarrollo, pruebas y producción separados. — 🟡 parcial: GitHub Actions y .venv reproducible; faltan entornos separados
- [ ] **RNF-MAN-05** registros (logs) estructurados y monitoreo de errores (por ejemplo Sentry). — 🟡 parcial: logging + Sentry opcional

## Integridad de datos

- [x] **RNF-INT-01** transacciones atómicas en reservas, pagos y comprobantes para evitar dobles reservas y numeración duplicada. ✅ fase 1
- [x] **RNF-INT-02** bloqueo concurrente al asignar habitaciones, de modo que dos recepcionistas no vendan la misma. ✅ fase 1
- [x] **RNF-INT-03** borrado lógico (nunca físico) de reservas, huéspedes y comprobantes. ✅ fase 0
