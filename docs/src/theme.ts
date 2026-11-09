/* 三個頁面共用：淺色／深色主題切換，以及給 ECharts 用的配色（從 theme.css 的 CSS 變數讀取）。
   首次繪製前套用主題（避免閃爍）由各頁 <head> 的 inline script 負責；
   本模組在 DOM 解析完後才執行，負責切換按鈕與跟隨系統設定。 */

export type Theme = "light" | "dark";

const KEY = "taiex-theme";
const root = document.documentElement;
const mq = window.matchMedia("(prefers-color-scheme: dark)");

function stored(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function current(): Theme {
  return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function apply(theme: Theme) {
  root.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.textContent = theme === "dark" ? "☀" : "☾";
    btn.title = theme === "dark" ? "切換為淺色" : "切換為深色";
  }
  window.dispatchEvent(new CustomEvent("themechange", { detail: theme }));
}

mq.addEventListener("change", (e) => {
  if (!stored()) apply(e.matches ? "dark" : "light");
});

const toggle = document.getElementById("theme-toggle");
if (toggle) {
  apply(current());
  toggle.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* 無痕模式等存不了就算了，本次仍會切換 */
    }
    apply(next);
  });
}

/* 取目前主題下的圖表配色 */
export function chartTheme() {
  const cs = getComputedStyle(root);
  const v = (name: string) => cs.getPropertyValue("--" + name).trim();
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
}

export type ChartTheme = ReturnType<typeof chartTheme>;
