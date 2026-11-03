(() => {
  const root = document.documentElement;
  const themeToggle = document.getElementById("theme-toggle");
  const syncTheme = () => {
    if (themeToggle) {
      themeToggle.setAttribute("aria-pressed", root.dataset.theme === "dark");
    }
  };
  if (themeToggle) {
    syncTheme();
    themeToggle.addEventListener("click", () => {
      const theme = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = theme;
      try { localStorage.setItem("theme", theme); } catch {}
      syncTheme();
    });
  }
  const nav = document.querySelector(".site-nav");
  const toggle = document.getElementById("nav-toggle");
  const links = document.getElementById("site-links");
  if (toggle && nav && links) {
    toggle.addEventListener("click", () => {
      const open = !nav.classList.contains("open");
      nav.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
    });
    for (const a of links.querySelectorAll("a")) {
      a.addEventListener("click", () => {
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      });
    }
  }
  if (nav) {
    new IntersectionObserver(([e]) => nav.classList.toggle("stuck", e.intersectionRatio < 1),
      { threshold: 1 }).observe(nav);
  }
})();
