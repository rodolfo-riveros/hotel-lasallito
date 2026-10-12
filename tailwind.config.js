/** Diseño base del PMS.
 *
 * Los colores de estado (`state`) se definen UNA sola vez aquí y se usan a
 * través de las clases `status-*` de static/src/input.css (RNF-UX-04).
 * La paleta está pensada para daltonismo y siempre va acompañada de ícono y
 * texto, nunca solo color.
 */
const colors = require("tailwindcss/colors");

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html", "./apps/**/*.py"],
  safelist: [{ pattern: /^status-/ }],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Cormorant Garamond"', "ui-serif", "Georgia", "serif"],
      },
      colors: {
        // Marca: granate andino. Se puede sobreescribir por propiedad con --brand.
        brand: {
          50: "#fbf3f4",
          100: "#f6e4e6",
          200: "#ecc6cb",
          300: "#dd9ba3",
          400: "#c86774",
          500: "#ad4251",
          600: "#93303f",
          700: "#7a1e2c",
          800: "#661b27",
          900: "#561a24",
          950: "#300a10",
        },
        gold: {
          50: "#fbf8ef",
          100: "#f4ecd4",
          200: "#e9d7a6",
          300: "#dbbd70",
          400: "#cfa54b",
          500: "#c08b36",
          600: "#a66d2c",
          700: "#865127",
          800: "#6f4226",
          900: "#5e3823",
        },
        ink: colors.stone,
        state: {
          available: "#0f7b5f",
          occupied: "#1d5fd1",
          dirty: "#b45309",
          cleaning: "#7c3aed",
          inspected: "#0e7490",
          blocked: "#475569",
          pending: "#a16207",
          confirmed: "#15803d",
          danger: "#c2410c",
          neutral: "#57534e",
        },
      },
      boxShadow: {
        soft: "0 1px 2px rgb(28 25 23 / 0.04), 0 4px 16px -4px rgb(28 25 23 / 0.08)",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
