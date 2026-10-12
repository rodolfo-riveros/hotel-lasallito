// Copia HTMX, Alpine y las fuentes a static/vendor para servirlas sin CDN
// (RNF-DIS-03: la recepción debe seguir operando con cortes de internet).
import { cpSync, mkdirSync } from "node:fs";

const out = "static/vendor";
mkdirSync(`${out}/fonts`, { recursive: true });

cpSync("node_modules/htmx.org/dist/htmx.min.js", `${out}/htmx.min.js`);
cpSync("node_modules/alpinejs/dist/cdn.min.js", `${out}/alpine.min.js`);
cpSync(
  "node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
  `${out}/fonts/inter-latin-wght-normal.woff2`,
);
cpSync(
  "node_modules/@fontsource-variable/inter/files/inter-latin-ext-wght-normal.woff2",
  `${out}/fonts/inter-latin-ext-wght-normal.woff2`,
);
for (const weight of ["500", "600", "700"]) {
  cpSync(
    `node_modules/@fontsource/cormorant-garamond/files/cormorant-garamond-latin-${weight}-normal.woff2`,
    `${out}/fonts/cormorant-garamond-latin-${weight}-normal.woff2`,
  );
}
console.log("Recursos copiados en", out);
