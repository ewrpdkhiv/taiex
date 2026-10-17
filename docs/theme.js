/* 三個頁面共用：淺色／深色主題切換，以及給 ECharts 用的配色（從 theme.css 的 CSS 變數讀取）。
   須在 <head> 同步載入，才能在首次繪製前套用主題、避免閃爍。 */
(function () {
  const KEY = "taiex-theme";
  const root = document.documentElement;
  const mq = window.matchMedia("(prefers-color-scheme: dark)");

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.textContent = theme === "dark" ? "☀" : "☾";
      btn.title = theme === "dark" ? "切換為淺色" : "切換為深色";
    }
    window.dispatchEvent(new CustomEvent("themechange", { detail: theme }));
  }

  apply(stored() || (mq.matches ? "dark" : "light"));

  mq.addEventListener("change", (e) => {
    if (!stored()) apply(e.matches ? "dark" : "light");
  });

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    apply(root.getAttribute("data-theme"));
    btn.addEventListener("click", () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch (e) {}
      apply(next);
    });
  });

  /* 取目前主題下的圖表配色 */
  window.chartTheme = function () {
    const cs = getComputedStyle(root);
    const v = (name) => cs.getPropertyValue("--" + name).trim();
    return {
      bg: v("surface"),
      ink: v("ink"),
      ink2: v("ink-2"),
      ink3: v("ink-3"),
      rule: v("rule"),
      ruleStrong: v("rule-strong"),
      grid: v("chart-grid"),
      surface2: v("surface-2"),
      accent: v("accent"),
      accentSoft: v("accent-soft"),
      down: v("down"),
      downSoft: v("down-soft"),
      downLine: v("down-line"),
      up: v("up"),
      upSoft: v("up-soft"),
      upLine: v("up-line"),
      warn: v("warn"),
      warnSoft: v("warn-soft"),
      candleUp: v("candle-up"),
      candleDown: v("candle-down"),
      event: v("chart-event"),
      eventLabel: v("chart-event-label"),
      eventLabelBg: v("chart-event-label-bg"),
      nested: v("chart-nested"),
      nestedSoft: v("chart-nested-soft"),
      nestedLabel: v("chart-nested-label"),
      nestedLabelBg: v("chart-nested-label-bg"),
      mono: v("font-mono"),
    };
  };
})();
