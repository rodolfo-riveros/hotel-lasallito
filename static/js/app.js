// Comportamiento común de la interfaz (Alpine.js + HTMX).
document.addEventListener("alpine:init", () => {
  Alpine.data("shell", () => ({
    menuOpen: false,
    helpOpen: false,
    dark: document.documentElement.classList.contains("dark"),
    clock: "",
    init() {
      const fmt = new Intl.DateTimeFormat("es-PE", {
        timeZone: "America/Lima",
        weekday: "long",
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      });
      const tick = () => (this.clock = fmt.format(new Date()));
      tick();
      setInterval(tick, 30000);
    },
    toggleTheme() {
      this.dark = !this.dark;
      document.documentElement.classList.toggle("dark", this.dark);
      try {
        localStorage.setItem("pms-theme", this.dark ? "dark" : "light");
      } catch (e) {}
    },
    // Atajos de teclado (RNF-UX-03). "g" seguido de una letra navega.
    pendingG: false,
    onKey(e) {
      const tag = (e.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag) || e.target.isContentEditable) {
        if (e.key === "Escape") e.target.blur();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "?") {
        this.helpOpen = !this.helpOpen;
        return;
      }
      if (e.key === "Escape") {
        this.helpOpen = false;
        this.menuOpen = false;
        return;
      }
      if (e.key === "/") {
        const search = document.querySelector("[data-search]");
        if (search) {
          e.preventDefault();
          search.focus();
        }
        return;
      }
      if (e.key === "n") {
        const create = document.querySelector("[data-shortcut-new]");
        if (create) create.click();
        return;
      }
      if (this.pendingG) {
        this.pendingG = false;
        const target = document.querySelector(`[data-goto="${e.key}"]`);
        if (target) window.location = target.getAttribute("href") || target.dataset.href;
        return;
      }
      if (e.key === "g") {
        this.pendingG = true;
        setTimeout(() => (this.pendingG = false), 1200);
      }
    },
  }));

  Alpine.data("toast", (timeout = 5000) => ({
    show: true,
    init() {
      if (timeout) setTimeout(() => (this.show = false), timeout);
    },
  }));
});

// Confirmación antes de acciones destructivas (RNF-UX-05): hx-confirm o data-confirm.
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// PWA: registra el service worker (instalable y con contingencia sin internet, RNF-DIS-03).
if ("serviceWorker" in navigator && location.protocol !== "file:") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  });
}
