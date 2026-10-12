---
fecha: 2026-10-12
fase: 0
estado: aceptada
tags: [decision, frontend, diseño]
---
# Decisión: frontend servido localmente

**Contexto.** En Cusco hay cortes de internet frecuentes y la recepción debe seguir operando (sección 2,
RNF-DIS-03).

**Decisión.**
- Tailwind 3.4 se compila con npm a `static/css/app.css`. El archivo se versiona para no depender de Node
  en el servidor.
- HTMX 2, Alpine 3 y las fuentes (Inter y Cormorant Garamond) se copian a `static/vendor`. No se carga
  nada desde un CDN.
- Identidad visual: granate andino (`brand-700 #7a1e2c`) con acento dorado; títulos en serif.
- Colores de estado definidos **una sola vez**. Siempre van con color, ícono y texto (RNF-UX-04).
- Modo oscuro opcional y atajos de teclado (`g`+letra, `/`, `n`, `?`).
