import { byId } from "./dom";
import "./theme";
import type { DcaData, DcaPeriod, DcaResult, DipCompare, Yearly, YearlyResult } from "./types";

function rateStr(r: number | null | undefined): string {
  if (r == null) return "—";
  return (r >= 0 ? "+" : "") + r.toFixed(2) + "%";
}
function rateClass(r: number | null | undefined): string {
  if (r == null) return "";
  return r >= 0 ? "pos" : "neg";
}

type FilterKey = "market" | "type" | "special";
type ColKey = (typeof COL_DEFS)[number]["key"];

let _cache: Partial<Record<DcaPeriod, DcaResult[]>> = {};
let _results: DcaResult[] = [];
let _dipCompare: DipCompare[] = [];
let _yearly: Yearly = { years: [], ytd_year: null, results: [] };
let _yearlySortKey = "avg";
let _sortKey: ColKey = "irr";
const _portfolio = new Set<string>();
const _visibleCols = new Set<ColKey>(["return_rate", "irr", "max_drawdown", "calmar"]);
const _filters: { market: string | null; type: string | null; special: Set<string> } = {
  market: null,
  type: null,
  special: new Set(),
};

const FILTER_GROUPS: { key: FilterKey; label: string; chips: { val: string; label: string }[] }[] = [
  {
    key: "market",
    label: "市場",
    chips: [
      { val: "tw", label: "台股" },
      { val: "us", label: "美股" },
    ],
  },
  {
    key: "type",
    label: "類型",
    chips: [
      { val: "stock", label: "個股" },
      { val: "etf", label: "ETF" },
    ],
  },
  {
    key: "special",
    label: "特殊",
    chips: [
      { val: "finance", label: "金融股" },
      { val: "shipping", label: "航運" },
      { val: "biotech", label: "生技" },
      { val: "leveraged", label: "槓桿ETF" },
      { val: "no_leverage", label: "無槓桿ETF" },
    ],
  },
];

function matchesSpecial(tags: string[], val: string): boolean {
  if (val === "no_leverage") return tags.includes("etf") && !tags.includes("leveraged");
  return tags.includes(val);
}

function applyFilters<T extends { tags?: string[] }>(results: T[]): T[] {
  return results.filter((d) => {
    const tags = d.tags || [];
    if (_filters.market && !tags.includes(_filters.market)) return false;
    if (_filters.type && !tags.includes(_filters.type)) return false;
    if (
      _filters.special.size > 0 &&
      ![..._filters.special].some((s) => matchesSpecial(tags, s))
    )
      return false;
    return true;
  });
}

function setFilter(groupKey: FilterKey, val: string) {
  if (groupKey === "special") {
    if (_filters.special.has(val)) _filters.special.delete(val);
    else _filters.special.add(val);
  } else {
    _filters[groupKey] = _filters[groupKey] === val ? null : val;
  }
  byId("filter-bar").innerHTML = renderFilterBar();
  byId("table-container").innerHTML = renderTable();
  byId("dip-compare-container").innerHTML = renderDipCompareTable();
  byId("yearly-container").innerHTML = renderYearlyTable();
}

function renderFilterBar(): string {
  return FILTER_GROUPS.map((g) => {
    const chips = g.chips
      .map((c) => {
        const isActive =
          g.key === "special" ? _filters.special.has(c.val) : _filters[g.key] === c.val;
        return `<button class="filter-chip ${isActive ? "active" : ""}" onclick="setFilter('${g.key}','${c.val}')">${c.label}</button>`;
      })
      .join("");
    return `<div class="filter-group"><span class="filter-label">${g.label}</span>${chips}</div>`;
  }).join("");
}

const COL_DEFS = [
  { key: "invested", label: "成本", sortable: true },
  { key: "shares", label: "股數", sortable: false },
  { key: "market_value", label: "市值", sortable: true },
  { key: "last_price", label: "收盤價", sortable: true },
  { key: "market_cap", label: "股票市值", sortable: true },
  { key: "pnl", label: "損益", sortable: true },
  { key: "return_rate", label: "總報酬", sortable: true },
  { key: "irr", label: "XIRR", sortable: true },
  { key: "max_drawdown", label: "最大回撤", sortable: true },
  { key: "calmar", label: "Calmar", sortable: true },
] as const;

function moneyStr(v: number | null | undefined): string {
  if (v == null) return "—";
  return Math.round(v).toLocaleString();
}
function sharesStr(v: number | null): string {
  if (v == null) return "—";
  return v.toFixed(2);
}
function mktCapStr(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return (v / 1e12).toFixed(2) + " 兆";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + " 億";
  if (v >= 1e4) return (v / 1e4).toFixed(2) + " 萬";
  return Math.round(v).toLocaleString();
}

function pnlVal(d: DcaResult): number | null {
  if (d.invested == null || d.reinvest.market_value == null) return null;
  return d.reinvest.market_value - d.invested;
}
function pnlStr(v: number | null): string {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + Math.round(v).toLocaleString();
}

function sortValue(d: DcaResult, key: ColKey): number {
  if (key === "invested") return d.invested ?? -Infinity;
  if (key === "market_value") return d.reinvest.market_value ?? -Infinity;
  if (key === "last_price") return d.last_price ?? -Infinity;
  if (key === "market_cap") return d.market_cap ?? -Infinity;
  if (key === "pnl") return pnlVal(d) ?? -Infinity;
  const v = d.reinvest[key];
  if (v == null) return -Infinity;
  return key === "max_drawdown" ? Math.abs(v) : v;
}

function renderToggles(): string {
  return (
    '<span class="label">欄位：</span>' +
    COL_DEFS.map(
      (c) =>
        `<button class="col-chip ${_visibleCols.has(c.key) ? "on" : ""}" onclick="toggleCol('${c.key}')">${c.label}</button>`,
    ).join("")
  );
}

function toggleCol(key: ColKey) {
  if (_visibleCols.has(key)) _visibleCols.delete(key);
  else _visibleCols.add(key);
  byId("col-toggles").innerHTML = renderToggles();
  byId("table-container").innerHTML = renderTable();
}

function renderTable(): string {
  const filtered = applyFilters(_results);
  if (!filtered.length) {
    return _results.length
      ? '<div class="loading-msg">無符合篩選條件的資料</div>'
      : '<div class="loading-msg">資料尚未就緒，請稍後重新整理</div>';
  }

  const vis = (key: ColKey) => _visibleCols.has(key);
  const sorted = [...filtered].sort((a, b) => sortValue(b, _sortKey) - sortValue(a, _sortKey));

  const maxIrr = Math.max(...sorted.map((d) => Math.abs(d.reinvest.irr ?? 0)));
  const maxDd = Math.max(...sorted.map((d) => Math.abs(d.reinvest.max_drawdown ?? 0)));
  const maxCalmar = Math.max(...sorted.map((d) => d.reinvest.calmar ?? 0));

  const rows = sorted
    .map((d, i) => {
      const re = d.reinvest;
      const irrBarW = maxIrr > 0 ? Math.round((Math.abs(re.irr ?? 0) / maxIrr) * 60) : 0;
      const ddBarW = maxDd > 0 ? Math.round((Math.abs(re.max_drawdown ?? 0) / maxDd) * 60) : 0;
      const calmarBarW = maxCalmar > 0 ? Math.round(((re.calmar ?? 0) / maxCalmar) * 60) : 0;
      const calmarClass =
        re.calmar == null ? "" : re.calmar >= 1 ? "pos" : re.calmar >= 0.5 ? "mid" : "neg";
      const pnl = pnlVal(d);
      const sel = _portfolio.has(d.ticker);
      return `
      <tr class="${sel ? "selected" : ""}" onclick="togglePortfolio('${d.ticker}')">
        <td>${sel ? "✓" : i + 1}</td>
        <td><div class="ticker">${d.ticker}</div><div class="name">${d.name}</div></td>
        ${vis("invested") ? `<td>${moneyStr(d.invested)}</td>` : ""}
        ${vis("shares") ? `<td>${sharesStr(re.shares)}</td>` : ""}
        ${vis("market_value") ? `<td>${moneyStr(re.market_value)}</td>` : ""}
        ${vis("last_price") ? `<td>${d.last_price != null ? d.last_price.toLocaleString() : "—"}</td>` : ""}
        ${vis("market_cap") ? `<td>${mktCapStr(d.market_cap)}</td>` : ""}
        ${vis("pnl") ? `<td><span class="${rateClass(pnl)}">${pnlStr(pnl)}</span></td>` : ""}
        ${vis("return_rate") ? `<td><span class="${rateClass(re.return_rate)}">${rateStr(re.return_rate)}</span></td>` : ""}
        ${vis("irr") ? `<td><div class="bar-wrap"><span class="${rateClass(re.irr)}">${rateStr(re.irr)}</span><div class="bar" style="width:${irrBarW}px"></div></div></td>` : ""}
        ${vis("max_drawdown") ? `<td><div class="bar-wrap"><span class="neg">${re.max_drawdown != null ? re.max_drawdown.toFixed(2) + "%" : "—"}</span><div class="bar neg-bar" style="width:${ddBarW}px"></div></div></td>` : ""}
        ${vis("calmar") ? `<td><div class="bar-wrap"><span class="${calmarClass}">${re.calmar != null ? re.calmar.toFixed(2) : "—"}</span><div class="bar" style="width:${calmarBarW}px"></div></div></td>` : ""}
      </tr>`;
    })
    .join("");

  const arrow = "▼";
  function thClass(key: ColKey) {
    return _sortKey === key ? "th-active" : "th-sort";
  }
  function thLabel(key: ColKey, label: string) {
    return `<th class="${thClass(key)}" onclick="setSort('${key}')">${label} <span class="sort-arrow">${_sortKey === key ? arrow : "↕"}</span></th>`;
  }

  return `
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>標的</th>
          ${vis("invested") ? thLabel("invested", "成本") : ""}
          ${vis("shares") ? "<th>股數</th>" : ""}
          ${vis("market_value") ? thLabel("market_value", "市值") : ""}
          ${vis("last_price") ? thLabel("last_price", "收盤價") : ""}
          ${vis("market_cap") ? thLabel("market_cap", "股票市值") : ""}
          ${vis("pnl") ? thLabel("pnl", "損益") : ""}
          ${vis("return_rate") ? thLabel("return_rate", "總報酬") : ""}
          ${vis("irr") ? thLabel("irr", "XIRR") : ""}
          ${vis("max_drawdown") ? thLabel("max_drawdown", "最大回撤") : ""}
          ${vis("calmar") ? thLabel("calmar", "Calmar") : ""}
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderDipCompareTable(): string {
  const rows = applyFilters(_dipCompare);
  if (!rows.length) {
    return _dipCompare.length
      ? '<div class="loading-msg">無符合篩選條件的資料</div>'
      : '<div class="loading-msg">資料尚未就緒，請稍後重新整理</div>';
  }
  const withDelta = rows.map((d) => ({
    ...d,
    deltaIrr:
      d.baseline.irr != null && d.dip_buy.irr != null ? d.dip_buy.irr - d.baseline.irr : null,
  }));
  const sorted = [...withDelta].sort(
    (a, b) => (b.deltaIrr ?? -Infinity) - (a.deltaIrr ?? -Infinity),
  );
  const ddStr = (v: number | null) => (v != null ? v.toFixed(2) + "%" : "—");

  const rows_ = sorted
    .map((d, i) => {
      const b = d.baseline,
        dp = d.dip_buy;
      const deltaClass = d.deltaIrr == null ? "" : d.deltaIrr >= 0 ? "pos" : "neg";
      const deltaStr =
        d.deltaIrr != null ? (d.deltaIrr >= 0 ? "+" : "") + d.deltaIrr.toFixed(2) + "%" : "—";
      return `<tr>
        <td>${i + 1}</td>
        <td><div class="ticker">${d.ticker}</div><div class="name">${d.name}</div></td>
        <td>${d.dip_trigger_count}</td>
        <td>${moneyStr(b.invested)}</td>
        <td>${moneyStr(dp.invested)}</td>
        <td><span class="${rateClass(b.irr)}">${rateStr(b.irr)}</span></td>
        <td><span class="${rateClass(dp.irr)}">${rateStr(dp.irr)}</span></td>
        <td><span class="${deltaClass}">${deltaStr}</span></td>
        <td>${ddStr(b.max_drawdown)}</td>
        <td>${ddStr(dp.max_drawdown)}</td>
      </tr>`;
    })
    .join("");

  return `<table>
    <thead>
      <tr>
        <th>#</th>
        <th>標的</th>
        <th>加碼次數</th>
        <th>固定投入</th>
        <th>加碼投入</th>
        <th>固定 XIRR</th>
        <th>加碼 XIRR</th>
        <th>XIRR 差異</th>
        <th>固定回撤</th>
        <th>加碼回撤</th>
      </tr>
    </thead>
    <tbody>${rows_}</tbody>
  </table>`;
}

// 完整年度（不含 YTD）的 XIRR 平均與正報酬年數
function yearlySummary(d: YearlyResult) {
  const irrs = _yearly.years
    .filter((y) => y !== _yearly.ytd_year)
    .map((y) => d.by_year[y]?.irr)
    .filter((v): v is number => v != null);
  if (!irrs.length) return { avg: null, posYears: null, n: 0 };
  return {
    avg: irrs.reduce((s, v) => s + v, 0) / irrs.length,
    posYears: irrs.filter((v) => v > 0).length,
    n: irrs.length,
  };
}

/* key：年份字串，或 "avg"（平均）、"pos"（正報酬年數） */
function yearlySortValue(d: YearlyResult, key: string): number {
  if (key === "avg") return yearlySummary(d).avg ?? -Infinity;
  if (key === "pos") return yearlySummary(d).posYears ?? -Infinity;
  return d.by_year[key]?.irr ?? -Infinity;
}

function setYearlySort(key: string) {
  _yearlySortKey = key;
  byId("yearly-container").innerHTML = renderYearlyTable();
}

function renderYearlyTable(): string {
  const rows = applyFilters(_yearly.results);
  if (!rows.length) {
    return _yearly.results.length
      ? '<div class="loading-msg">無符合篩選條件的資料</div>'
      : '<div class="loading-msg">資料尚未就緒，請稍後重新整理</div>';
  }
  const years = _yearly.years.map(String);
  const ytd = String(_yearly.ytd_year);
  const sorted = [...rows].sort(
    (a, b) => yearlySortValue(b, _yearlySortKey) - yearlySortValue(a, _yearlySortKey),
  );

  const body = sorted
    .map((d, i) => {
      const cells = years
        .map((y) => {
          const v = d.by_year[y];
          if (!v) return "<td>—</td>";
          const partial = v.months < 12 && y !== ytd;
          return `<td class="${partial ? "partial" : ""}" title="${y}：投入 ${v.months} 次・總報酬 ${rateStr(v.return_rate)}"><span class="${rateClass(v.irr)}">${rateStr(v.irr)}</span></td>`;
        })
        .join("");
      const sum = yearlySummary(d);
      return `<tr>
        <td>${i + 1}</td>
        <td><div class="ticker">${d.ticker}</div><div class="name">${d.name}</div></td>
        ${cells}
        <td class="avg-col"><span class="${rateClass(sum.avg)}">${rateStr(sum.avg)}</span></td>
        <td>${sum.posYears != null ? `${sum.posYears} / ${sum.n}` : "—"}</td>
      </tr>`;
    })
    .join("");

  const th = (key: string, label: string, cls = "") =>
    `<th class="${cls} ${_yearlySortKey === key ? "th-active" : "th-sort"}" onclick="setYearlySort('${key}')">${label} <span class="sort-arrow">${_yearlySortKey === key ? "▼" : "↕"}</span></th>`;

  return `<table class="yearly-table">
    <thead>
      <tr>
        <th>#</th>
        <th>標的</th>
        ${years.map((y) => th(y, y === ytd ? `${y} YTD` : y)).join("")}
        ${th("avg", "平均", "avg-col")}
        ${th("pos", "正報酬年")}
      </tr>
    </thead>
    <tbody>${body}</tbody>
  </table>`;
}

function setSort(key: ColKey) {
  _sortKey = key;
  byId("table-container").innerHTML = renderTable();
}

function togglePortfolio(ticker: string) {
  if (_portfolio.has(ticker)) _portfolio.delete(ticker);
  else _portfolio.add(ticker);
  byId("table-container").innerHTML = renderTable();
  updatePortfolioBar();
}

function clearPortfolio() {
  _portfolio.clear();
  byId("table-container").innerHTML = renderTable();
  updatePortfolioBar();
}

function updatePortfolioBar() {
  const bar = byId("portfolio-bar");
  const selected = _results.filter((d) => _portfolio.has(d.ticker));
  if (!selected.length) {
    bar.classList.remove("visible");
    document.body.classList.remove("has-portfolio");
    return;
  }
  bar.classList.add("visible");
  document.body.classList.add("has-portfolio");

  byId("portfolio-chips").innerHTML = selected
    .map(
      (d) =>
        `<span class="portfolio-chip" onclick="event.stopPropagation();togglePortfolio('${d.ticker}')" title="點擊移除">${d.ticker} ${d.name} ✕</span>`,
    )
    .join("");

  if (selected.length >= 2) {
    const totalInvested = selected.reduce((s, d) => s + (d.invested ?? 0), 0);
    const totalMV = selected.reduce((s, d) => s + (d.reinvest.market_value ?? 0), 0);
    const combinedReturn =
      totalInvested > 0 ? ((totalMV - totalInvested) / totalInvested) * 100 : null;
    const pnl = totalMV - totalInvested;
    const retClass = combinedReturn == null ? "" : combinedReturn >= 0 ? "pos" : "neg";
    const pnlClass = pnl >= 0 ? "pos" : "neg";
    byId("portfolio-stats").innerHTML = `
      <div class="portfolio-stat">
        <span class="s-label">總投入</span>
        <span class="s-val">${Math.round(totalInvested).toLocaleString()}</span>
      </div>
      <div class="portfolio-stat">
        <span class="s-label">總市值</span>
        <span class="s-val">${Math.round(totalMV).toLocaleString()}</span>
      </div>
      <div class="portfolio-stat">
        <span class="s-label">損益</span>
        <span class="s-val ${pnlClass}">${pnl >= 0 ? "+" : ""}${Math.round(pnl).toLocaleString()}</span>
      </div>
      <div class="portfolio-stat">
        <span class="s-label">組合總報酬</span>
        <span class="s-val ${retClass}">${combinedReturn != null ? (combinedReturn >= 0 ? "+" : "") + combinedReturn.toFixed(2) + "%" : "—"}</span>
      </div>`;
  } else {
    byId("portfolio-stats").innerHTML = `<span class="portfolio-hint">再選一檔計算組合報酬</span>`;
  }
}

function setPeriod(key: DcaPeriod, btn: HTMLElement) {
  _results = _cache[key] || [];
  document.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  const first = _results[0];
  if (first) {
    byId("period-text").textContent = `${first.start_date} ～ ${first.end_date}`;
  }
  byId("filter-bar").innerHTML = renderFilterBar();
  byId("table-container").innerHTML = renderTable();
  updatePortfolioBar();
}

async function load() {
  try {
    const res = await fetch("data/dca.json");
    const data: DcaData = await res.json();
    const err = byId("error-banner");
    if (data.error) {
      err.style.display = "block";
      err.textContent = "資料更新失敗：" + data.error;
    } else {
      err.style.display = "none";
    }
    byId("last-updated").textContent = data.last_updated || "—";

    _cache = {
      "10y": data.results_10y || [],
      "5y": data.results_5y || [],
      crash_10y: data.results_crash_10y || [],
      crash_5y: data.results_crash_5y || [],
      covid: data.results_covid || [],
    };
    _results = _cache["10y"] || [];
    const first = _results[0];
    if (first) {
      byId("period-text").textContent = `${first.start_date} ～ ${first.end_date}`;
    }
    byId("filter-bar").innerHTML = renderFilterBar();
    byId("table-container").innerHTML = renderTable();
    _dipCompare = data.dip_buy_comparison || [];
    byId("dip-compare-container").innerHTML = renderDipCompareTable();
    _yearly = data.yearly || _yearly;
    byId("yearly-container").innerHTML = renderYearlyTable();
  } catch (e) {
    console.error(e);
  }
}

// HTML 裡的 onclick（含上面組出來的 HTML 字串）會呼叫這些函式，模組內的函式預設不是全域的
Object.assign(window, {
  setPeriod,
  setFilter,
  toggleCol,
  setSort,
  setYearlySort,
  togglePortfolio,
  clearPortfolio,
});

byId("col-toggles").innerHTML = renderToggles();
load();
