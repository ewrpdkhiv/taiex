import * as echarts from "echarts";
import type {
  DefaultLabelFormatterCallbackParams as CallbackDataParams,
  TooltipComponentFormatterCallbackParams,
} from "echarts";
import html2canvas from "html2canvas";
import { byId, query } from "./dom";
import {
  addEventBand,
  layoutEventLabels,
  type KlineOption,
  type MarkAreaPair,
} from "./kline-events";
import { loadOhlc } from "./ohlc";
import { chartTheme } from "./theme";
import type {
  Bear,
  BearData,
  DayRecord,
  InstitutionKey,
  InstitutionYear,
  HolidayEvent,
  MarginRecord,
  Ohlc,
  PostEvent,
  RankingKey,
  Stats,
  Streak,
  TaiexData,
  TodayIndex,
  TodayInstitution,
  TodayMaintenance,
  TodayMargin,
} from "./types";

const REFRESH_MS = 3600 * 1000;
let currentType = "drops-pct";
let currentPeriod = "20y";
let _data: TaiexData | null = null;
const _sortState: Record<string, SortMode> = {};

const fmt = (n: number) =>
  n.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const recStr = (days: number | null | undefined, none = "—") =>
  days === 0 ? "當日" : days != null ? days + " 天" : none;

function pctRow(r: DayRecord, cls: string) {
  return `<tr class="clickable-drop" data-drop="${encodeURIComponent(JSON.stringify(r))}">
    <td>${r.rank}</td>
    <td class="date">${r.date}</td>
    <td class="col-close">${fmt(r.close)}</td>
    <td class="col-prev">${fmt(r.prev_close)}</td>
    <td class="${cls} col-pct">${r.change_pct.toFixed(2)}%</td>
    <td class="recovery">${recStr(r.fallback_days, "未回落")}</td>
    <td class="event col-event">${r.event}</td>
  </tr>`;
}

function dropPctRow(r: DayRecord, cls: string) {
  return `<tr class="clickable-drop" data-drop="${encodeURIComponent(JSON.stringify(r))}">
    <td>${r.rank}</td>
    <td class="date">${r.date}</td>
    <td class="col-close">${fmt(r.close)}</td>
    <td class="col-prev">${fmt(r.prev_close)}</td>
    <td class="${cls} col-pct">${r.change_pct.toFixed(2)}%</td>
    <td class="recovery">${recStr(r.recovery_days)}</td>
    <td class="event col-event">${r.event}</td>
  </tr>`;
}

function ptRow(r: DayRecord, cls: string) {
  return `<tr class="clickable-drop" data-drop="${encodeURIComponent(JSON.stringify(r))}">
    <td>${r.rank}</td>
    <td class="date">${r.date}</td>
    <td class="col-close">${fmt(r.close)}</td>
    <td class="col-prev">${fmt(r.prev_close)}</td>
    <td class="${cls}">${fmt(r.change_pt)}</td>
    <td class="col-pct pct">${r.change_pct.toFixed(2)}%</td>
    <td class="recovery">${recStr(r.fallback_days, "未回落")}</td>
    <td class="event col-event">${r.event}</td>
  </tr>`;
}

function dropPtRow(r: DayRecord, cls: string) {
  return `<tr class="clickable-drop" data-drop="${encodeURIComponent(JSON.stringify(r))}">
    <td>${r.rank}</td>
    <td class="date">${r.date}</td>
    <td class="col-close">${fmt(r.close)}</td>
    <td class="col-prev">${fmt(r.prev_close)}</td>
    <td class="${cls}">${fmt(r.change_pt)}</td>
    <td class="col-pct pct">${r.change_pct.toFixed(2)}%</td>
    <td class="recovery">${recStr(r.recovery_days)}</td>
    <td class="event col-event">${r.event}</td>
  </tr>`;
}

// 外資／投信的買超、賣超列（key 為金額欄位）；回落／回升天數欄位買超看回落、賣超看回升
function institutionRow(key: InstitutionKey, buy: boolean) {
  return (r: DayRecord) => {
    const net = r[key] ?? 0;
    const pctCls = r.change_pct < 0 ? "drop" : "gain";
    const sign = r.change_pct > 0 ? "+" : "";
    return `<tr class="clickable-drop" data-drop="${encodeURIComponent(JSON.stringify(r))}">
    <td>${r.rank}</td>
    <td class="date">${r.date}</td>
    <td class="${buy ? "gain" : "drop"}">${buy ? "+" : ""}${fmt(net)}</td>
    <td class="col-close">${fmt(r.close)}</td>
    <td class="col-prev">${fmt(r.prev_close)}</td>
    <td class="${pctCls} col-pct">${sign}${r.change_pct.toFixed(2)}%</td>
    <td class="recovery">${buy ? recStr(r.fallback_days, "未回落") : recStr(r.recovery_days)}</td>
    <td class="event col-event">${r.event}</td>
  </tr>`;
  };
}

const foreignBuyRow = institutionRow("foreign_net", true);
const foreignSellRow = institutionRow("foreign_net", false);
const trustBuyRow = institutionRow("trust_net", true);
const trustSellRow = institutionRow("trust_net", false);

function marginRow(r: MarginRecord) {
  const isGain = r.margin_change > 0;
  const pctCls = r.change_pct < 0 ? "drop" : "gain";
  const sign = r.change_pct > 0 ? "+" : "";
  return `<tr class="clickable-drop" data-drop="${encodeURIComponent(JSON.stringify(r))}">
    <td>${r.rank}</td>
    <td class="date">${r.date}</td>
    <td class="${isGain ? "gain" : "drop"}">${isGain ? "+" : ""}${fmt(r.margin_change)}</td>
    <td>${fmt(r.margin_balance)}</td>
    <td class="col-close">${fmt(r.close)}</td>
    <td class="col-prev">${fmt(r.prev_close)}</td>
    <td class="${pctCls} col-pct">${sign}${r.change_pct.toFixed(2)}%</td>
    <td class="recovery">${
      isGain ? recStr(r.fallback_days, "未回落") : recStr(r.recovery_days)
    }</td>
    <td class="event col-event">${r.event}</td>
  </tr>`;
}

interface TableConfig {
  key: RankingKey;
  /* 方法語法：外資／融資的列函式吃的是 DayRecord 的子型別，資料與函式的對應由下表保證 */
  fn(r: DayRecord, cls: string): string;
  cls: string;
  cols: number;
}

const TABLE_CONFIG: Record<string, TableConfig> = {
  "t-drops-pct-20y": { key: "drops_20y", fn: dropPctRow, cls: "drop", cols: 7 },
  "t-drops-pct-10y": { key: "drops_10y", fn: dropPctRow, cls: "drop", cols: 7 },
  "t-drops-pct-5y": { key: "drops_5y", fn: dropPctRow, cls: "drop", cols: 7 },
  "t-drops-pct-all": { key: "drops_all", fn: dropPctRow, cls: "drop", cols: 7 },
  "t-gains-pct-20y": { key: "gains_20y", fn: pctRow, cls: "gain", cols: 7 },
  "t-gains-pct-10y": { key: "gains_10y", fn: pctRow, cls: "gain", cols: 7 },
  "t-gains-pct-5y": { key: "gains_5y", fn: pctRow, cls: "gain", cols: 7 },
  "t-gains-pct-all": { key: "gains_all", fn: pctRow, cls: "gain", cols: 7 },
  "t-drops-pt-20y": { key: "drops_pt_20y", fn: dropPtRow, cls: "drop", cols: 8 },
  "t-drops-pt-10y": { key: "drops_pt_10y", fn: dropPtRow, cls: "drop", cols: 8 },
  "t-drops-pt-5y": { key: "drops_pt_5y", fn: dropPtRow, cls: "drop", cols: 8 },
  "t-drops-pt-all": { key: "drops_pt_all", fn: dropPtRow, cls: "drop", cols: 8 },
  "t-gains-pt-20y": { key: "gains_pt_20y", fn: ptRow, cls: "gain", cols: 8 },
  "t-gains-pt-10y": { key: "gains_pt_10y", fn: ptRow, cls: "gain", cols: 8 },
  "t-gains-pt-5y": { key: "gains_pt_5y", fn: ptRow, cls: "gain", cols: 8 },
  "t-gains-pt-all": { key: "gains_pt_all", fn: ptRow, cls: "gain", cols: 8 },
  "t-foreign-sells-20y": { key: "foreign_sells_20y", fn: foreignSellRow, cls: "drop", cols: 8 },
  "t-foreign-sells-10y": { key: "foreign_sells_10y", fn: foreignSellRow, cls: "drop", cols: 8 },
  "t-foreign-sells-5y": { key: "foreign_sells_5y", fn: foreignSellRow, cls: "drop", cols: 8 },
  "t-foreign-sells-all": { key: "foreign_sells_all", fn: foreignSellRow, cls: "drop", cols: 8 },
  "t-foreign-buys-20y": { key: "foreign_buys_20y", fn: foreignBuyRow, cls: "gain", cols: 8 },
  "t-foreign-buys-10y": { key: "foreign_buys_10y", fn: foreignBuyRow, cls: "gain", cols: 8 },
  "t-foreign-buys-5y": { key: "foreign_buys_5y", fn: foreignBuyRow, cls: "gain", cols: 8 },
  "t-foreign-buys-all": { key: "foreign_buys_all", fn: foreignBuyRow, cls: "gain", cols: 8 },
  "t-trust-sells-20y": { key: "trust_sells_20y", fn: trustSellRow, cls: "drop", cols: 8 },
  "t-trust-sells-10y": { key: "trust_sells_10y", fn: trustSellRow, cls: "drop", cols: 8 },
  "t-trust-sells-5y": { key: "trust_sells_5y", fn: trustSellRow, cls: "drop", cols: 8 },
  "t-trust-sells-all": { key: "trust_sells_all", fn: trustSellRow, cls: "drop", cols: 8 },
  "t-trust-buys-20y": { key: "trust_buys_20y", fn: trustBuyRow, cls: "gain", cols: 8 },
  "t-trust-buys-10y": { key: "trust_buys_10y", fn: trustBuyRow, cls: "gain", cols: 8 },
  "t-trust-buys-5y": { key: "trust_buys_5y", fn: trustBuyRow, cls: "gain", cols: 8 },
  "t-trust-buys-all": { key: "trust_buys_all", fn: trustBuyRow, cls: "gain", cols: 8 },
  "t-margin-increases-20y": { key: "margin_increases_20y", fn: marginRow, cls: "gain", cols: 9 },
  "t-margin-increases-10y": { key: "margin_increases_10y", fn: marginRow, cls: "gain", cols: 9 },
  "t-margin-increases-5y": { key: "margin_increases_5y", fn: marginRow, cls: "gain", cols: 9 },
  "t-margin-increases-all": { key: "margin_increases_all", fn: marginRow, cls: "gain", cols: 9 },
  "t-margin-decreases-20y": { key: "margin_decreases_20y", fn: marginRow, cls: "drop", cols: 9 },
  "t-margin-decreases-10y": { key: "margin_decreases_10y", fn: marginRow, cls: "drop", cols: 9 },
  "t-margin-decreases-5y": { key: "margin_decreases_5y", fn: marginRow, cls: "drop", cols: 9 },
  "t-margin-decreases-all": { key: "margin_decreases_all", fn: marginRow, cls: "drop", cols: 9 },
};

const SORT_MODES = ["original", "time-desc"] as const;
type SortMode = (typeof SORT_MODES)[number];
const SORT_LABELS: Record<SortMode, string> = { original: "依幅度", "time-desc": "時間 ↓" };

function sortedRows(rows: DayRecord[] | undefined, state: SortMode) {
  if (!rows || !rows.length) return rows;
  const r = [...rows];
  if (state === "time-desc") r.sort((a, b) => b.date.localeCompare(a.date));
  else r.sort((a, b) => a.rank - b.rank);
  return r;
}

function renderTable(
  id: string,
  rows: DayRecord[] | undefined,
  rowFn: TableConfig["fn"],
  cls: string,
  cols: number,
) {
  const tbody = byId(id);
  if (!rows || !rows.length) {
    tbody.innerHTML = `<tr><td colspan="${cols}" class="loading">暫無資料</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r) => rowFn(r, cls)).join("");
}

function streakRow(s: Streak, cls: string) {
  return `<tr>
    <td class="left date">${s.start_date} ~ ${s.end_date}</td>
    <td class="pct">${s.days} 天</td>
    <td class="${cls}">${s.cumulative_pct.toFixed(2)}%</td>
  </tr>`;
}

function renderStreaks(streaks: TaiexData["streaks"]) {
  const upBody = byId("t-streak-up");
  const downBody = byId("t-streak-down");
  if (!streaks || !streaks.up || !streaks.up.length) {
    upBody.innerHTML = `<tr><td colspan="3" class="loading">暫無資料</td></tr>`;
  } else {
    upBody.innerHTML = streaks.up.map((s) => streakRow(s, "gain")).join("");
  }
  if (!streaks || !streaks.down || !streaks.down.length) {
    downBody.innerHTML = `<tr><td colspan="3" class="loading">暫無資料</td></tr>`;
  } else {
    downBody.innerHTML = streaks.down.map((s) => streakRow(s, "drop")).join("");
  }
}

// 節日連假（中秋、過年、端午）明細列：連假期間、買進日、賣出日、報酬
function holidayDetailRow(ev: HolidayEvent) {
  const cls = ev.return_pct >= 0 ? "gain" : "drop";
  return `<tr>
    <td class="left date">${ev.holiday_start} ~ ${ev.holiday_end}（${ev.holiday_days} 天）</td>
    <td class="date">${ev.buy_date}（${ev.buy_close.toFixed(2)}）</td>
    <td class="date">${ev.sell_date}（${ev.sell_close.toFixed(2)}）</td>
    <td class="${cls}">${ev.return_pct.toFixed(2)}%</td>
  </tr>`;
}

// ── 大跌後 / 跌破均線後表現統計：共用渲染邏輯 ──
interface StatsPanel {
  tbodyId: string;
  badgeId: string;
  detailId: string;
  detailInfoId: string;
  detailTbodyId: string;
  /* 預設明細列多顯示的欄位（大跌幅度、大漲幅度、跌破均線幅度）；有 detailRow 時不用 */
  extraField?: "drop_pct" | "gain_pct" | "touch_pct";
  extraFieldCls?: string;
  getStats(data: TaiexData | null): Stats | undefined;
  badgeText(s: Stats): string;
  detailInfo(days: number, count: number): string;
  /* 方法語法：節日面板的事件是 HolidayEvent，由 getStats 對應的資料保證 */
  detailRow?(ev: HolidayEvent): string;
}

function maPanel(maDays: 20 | 60 | 120 | 240 | 1200 | 2400): StatsPanel {
  const key = `ma${maDays}` as const;
  return {
    tbodyId: `t-${key}-stats`,
    badgeId: `${key}-badge`,
    detailId: `${key}-detail`,
    detailInfoId: `${key}-detail-info`,
    detailTbodyId: `t-${key}-detail`,
    extraField: "touch_pct",
    getStats: (data) => data?.ma_touch_stats?.[key],
    badgeText: (s) => `跌破 ${s.ma_window} 日均線（樣本 ${s.sample_size} 次）`,
    detailInfo: (days, count) =>
      `跌破 ${maDays} 日均線之後 ${days} 個交易日的個別報酬（共 ${count} 次）`,
  };
}

const STATS_PANELS: Record<string, StatsPanel> = {
  "post-drop": {
    tbodyId: "t-post-drop-stats",
    badgeId: "post-drop-badge",
    detailId: "post-drop-detail",
    detailInfoId: "post-drop-detail-info",
    detailTbodyId: "t-post-drop-detail",
    extraField: "drop_pct",
    getStats: (data) => data?.post_drop_stats,
    badgeText: (s) => `跌幅 ≥ ${s.threshold}%（樣本 ${s.sample_size} 次）`,
    detailInfo: (days, count) => `大跌之後 ${days} 個交易日的個別報酬（共 ${count} 次）`,
  },
  "post-gain": {
    tbodyId: "t-post-gain-stats",
    badgeId: "post-gain-badge",
    detailId: "post-gain-detail",
    detailInfoId: "post-gain-detail-info",
    detailTbodyId: "t-post-gain-detail",
    extraField: "gain_pct",
    extraFieldCls: "gain",
    getStats: (data) => data?.post_gain_stats,
    badgeText: (s) => `漲幅 ≥ ${s.threshold}%（樣本 ${s.sample_size} 次）`,
    detailInfo: (days, count) => `大漲之後 ${days} 個交易日的個別報酬（共 ${count} 次）`,
  },
  ma20: maPanel(20),
  ma60: maPanel(60),
  ma120: maPanel(120),
  ma240: maPanel(240),
  ma1200: maPanel(1200),
  ma2400: maPanel(2400),
  "mid-autumn": {
    tbodyId: "t-mid-autumn-stats",
    badgeId: "mid-autumn-badge",
    detailId: "mid-autumn-detail",
    detailInfoId: "mid-autumn-detail-info",
    detailTbodyId: "t-mid-autumn-detail",
    getStats: (data) => data?.mid_autumn_stats,
    badgeText: (s) => `連假前最後一個交易日收盤買進（${s.sample_size} 年）`,
    detailInfo: (days, count) =>
      `連假後第 ${days} 個交易日收盤賣出的個別報酬（共 ${count} 年）`,
    detailRow: holidayDetailRow,
  },
  "lunar-new-year": {
    tbodyId: "t-lunar-new-year-stats",
    badgeId: "lunar-new-year-badge",
    detailId: "lunar-new-year-detail",
    detailInfoId: "lunar-new-year-detail-info",
    detailTbodyId: "t-lunar-new-year-detail",
    getStats: (data) => data?.lunar_new_year_stats,
    badgeText: (s) => `封關日收盤買進（${s.sample_size} 年）`,
    detailInfo: (days, count) =>
      `開紅盤後第 ${days} 個交易日收盤賣出的個別報酬（共 ${count} 年）`,
    detailRow: holidayDetailRow,
  },
  "dragon-boat": {
    tbodyId: "t-dragon-boat-stats",
    badgeId: "dragon-boat-badge",
    detailId: "dragon-boat-detail",
    detailInfoId: "dragon-boat-detail-info",
    detailTbodyId: "t-dragon-boat-detail",
    getStats: (data) => data?.dragon_boat_stats,
    badgeText: (s) => `連假前最後一個交易日收盤買進（${s.sample_size} 年）`,
    detailInfo: (days, count) =>
      `連假後第 ${days} 個交易日收盤賣出的個別報酬（共 ${count} 年）`,
    detailRow: holidayDetailRow,
  },
};

function renderStatsPanel(panelKey: string, stats: Stats | undefined) {
  const cfg = STATS_PANELS[panelKey];
  const tbody = byId(cfg.tbodyId);
  if (!stats || !stats.horizons || !stats.horizons.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="loading">暫無資料</td></tr>`;
    return;
  }
  byId(cfg.badgeId).textContent = cfg.badgeText(stats);
  closeStatsDetail(panelKey);
  tbody.innerHTML = stats.horizons
    .map((h) => {
      if (h.avg_return_pct == null) {
        return `<tr>
          <td class="left date">${h.days} 日</td>
          <td colspan="4" class="loading">樣本不足</td>
        </tr>`;
      }
      const cls = h.avg_return_pct >= 0 ? "gain" : "drop";
      return `<tr class="clickable-horizon" data-panel="${panelKey}" data-days="${h.days}">
        <td class="left date">${h.days} 日</td>
        <td class="${cls}">${h.avg_return_pct.toFixed(2)}%</td>
        <td class="pct">${h.median_return_pct.toFixed(2)}%</td>
        <td class="pct">${h.win_rate_pct.toFixed(1)}%</td>
        <td class="pct">${h.sample_size}</td>
      </tr>`;
    })
    .join("");
}

const _activeStatsRow: Record<string, HTMLElement | null> = {};

document.addEventListener("click", (e) => {
  const tr = (e.target as Element).closest<HTMLElement>("tr.clickable-horizon");
  if (!tr) return;
  const panelKey = tr.dataset.panel!;
  const days = Number(tr.dataset.days);
  _activeStatsRow[panelKey]?.classList.remove("active");
  _activeStatsRow[panelKey] = tr;
  tr.classList.add("active");
  openStatsDetail(panelKey, days);
});

function closeStatsDetail(panelKey: string) {
  const cfg = STATS_PANELS[panelKey];
  const outer = document.getElementById(cfg.detailId);
  if (outer) outer.style.display = "none";
  const active = _activeStatsRow[panelKey];
  if (active) {
    active.classList.remove("active");
    _activeStatsRow[panelKey] = null;
  }
}

function openStatsDetail(panelKey: string, days: number) {
  const cfg = STATS_PANELS[panelKey];
  const stats = cfg.getStats(_data);
  const horizon = stats && stats.horizons.find((h) => h.days === days);
  if (!horizon || !horizon.events) return;

  const outer = byId(cfg.detailId);
  byId(cfg.detailInfoId).textContent = cfg.detailInfo(days, horizon.events.length);

  const rows = [...horizon.events].reverse();
  const extraCls = cfg.extraFieldCls || "drop";
  byId(cfg.detailTbodyId).innerHTML = rows
    .map((ev) => {
      if (cfg.detailRow) return cfg.detailRow(ev as HolidayEvent);
      const post = ev as PostEvent;
      const extra = cfg.extraField ? post[cfg.extraField] : undefined;
      const cls = post.return_pct >= 0 ? "gain" : "drop";
      return `<tr>
        <td class="left date">${post.date}</td>
        <td class="${extraCls}">${extra != null ? extra.toFixed(2) + "%" : "—"}</td>
        <td class="${cls}">${post.return_pct.toFixed(2)}%</td>
      </tr>`;
    })
    .join("");

  outer.style.display = "block";
}

function fmtSigned(v: number, digits = 2) {
  return (v > 0 ? "+" : "") + v.toFixed(digits);
}

// 名次 + 同方向總日數；進前 10 名（排行表上看得到）時加強調色
function todayRankCell(rank: number, total: number) {
  const cls = rank <= 10 ? "today-rank top" : "today-rank";
  return `<span class="${cls}">第 ${rank.toLocaleString()} 名</span>
    <span class="today-total">/ ${total.toLocaleString()}</span>`;
}

function renderTodayIndex(t: TodayIndex | null | undefined): boolean {
  const el = byId("today-index");
  if (!t) {
    el.innerHTML = "";
    return false;
  }
  const isDrop = t.direction === "drop";
  const word = isDrop ? "跌" : "漲";
  el.dataset.color = t.direction;
  // 排名皆為全時（data.json 只產生 ranks.all）
  const r = t.ranks.all;
  const body =
    t.direction === "flat"
      ? `<div class="today-note">平盤，不列入排名</div>`
      : `<table>
          <thead><tr><th>${word}幅% 排名</th><th>${word}點 排名</th></tr></thead>
          <tbody><tr>
            <td>${todayRankCell(r.pct, r.total)}</td>
            <td>${todayRankCell(r.pt, r.total)}</td>
          </tr></tbody>
        </table>`;
  el.innerHTML = `
    <div class="today-head"><span>加權指數 收盤 ${t.close.toLocaleString()}</span><b>${t.date}</b></div>
    <div class="today-value ${t.direction}">${fmtSigned(t.change_pct)}%<small>${fmtSigned(t.change_pt)} 點</small></div>
    ${body}`;
  return true;
}

// 外資／投信單日買賣超（億元）＋ 在全時同方向排行的名次與連續天數
function renderTodayInstitution(
  id: string,
  name: string,
  key: InstitutionKey,
  f: TodayInstitution | null | undefined,
) {
  const el = byId(id);
  if (!f) {
    el.style.display = "none";
    return;
  }
  el.style.display = "";
  const isSell = f.direction === "sell";
  const word = isSell ? "賣超" : "買超";
  el.dataset.color = isSell ? "drop" : f.direction === "buy" ? "gain" : "";
  const r = f.ranks.all;
  const fmtYi = (v: number) =>
    Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const days = f.streak_days || [];
  // 有逐日明細時天數做成按鈕，點開列出這幾天（新到舊）的金額與合計
  const streakCell = days.length
    ? `<button type="button" class="today-rank today-streak-btn" aria-expanded="false"
         aria-controls="today-streak-list">${f.streak.toLocaleString()} 天</button>`
    : `<span class="today-rank">${(f.streak || 0).toLocaleString()} 天</span>`;
  const detail = days.length
    ? `<div class="today-streak-detail" id="today-streak-list" hidden>
        <table>
          <thead><tr><th>日期</th><th>${word}金額（億元）</th></tr></thead>
          <tbody>${days
            .slice()
            .reverse()
            .map((x) => `<tr><td>${x.date}</td><td>${fmtYi(x[key] ?? 0)}</td></tr>`)
            .join("")}</tbody>
          <tfoot><tr><td>合計 ${days.length} 天</td><td>${fmtYi(
            days.reduce((sum, x) => sum + (x[key] ?? 0), 0),
          )}</td></tr></tfoot>
        </table>
      </div>`
    : "";
  const body =
    f.direction === "flat"
      ? `<div class="today-note">買賣超為 0，不列入排名</div>`
      : `<table>
          <thead><tr><th>${word}金額排名</th>${f.streak ? `<th>連續${word}</th>` : ""}</tr></thead>
          <tbody><tr>
            <td>${todayRankCell(r.rank, r.total)}</td>
            ${f.streak ? `<td>${streakCell}</td>` : ""}
          </tr></tbody>
        </table>${detail}`;
  el.innerHTML = `
    <div class="today-head"><span>${name}${f.direction === "flat" ? "買賣超" : word}</span>
      <span class="today-head-right"><b>${f.date}</b><button type="button" class="export-btn">⬇ PNG</button></span></div>
    <div class="today-value ${el.dataset.color}">${fmtYi(f[key] ?? 0)}<small>億元</small></div>
    ${body}`;
  // 只輸出這張卡；固定寬度，手機上輸出也是同樣版面
  query(".export-btn", el).addEventListener("click", () => {
    exportPng(el, `TAIEX_${name}${word}_${f.date}.png`, (c) => {
      c.style.width = "380px";
    });
  });
  const btn = el.querySelector<HTMLElement>(".today-streak-btn");
  if (btn) {
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      query(".today-streak-detail", el).hidden = !open;
    });
  }
}

const fmt2 = (v: number) =>
  v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtSignedMinus = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "") + fmt2(Math.abs(v));

// 融資餘額增減（億元）＋ 在全時同方向排行的名次
function renderTodayMargin(margin: TodayMargin | null | undefined) {
  const el = byId("today-margin");
  if (!margin) {
    el.style.display = "none";
    return;
  }
  el.style.display = "";
  const dir = margin.change > 0 ? "gain" : margin.change < 0 ? "drop" : "";
  el.dataset.color = dir;
  const word = margin.change > 0 ? "增加" : margin.change < 0 ? "減少" : "持平";
  // 持平不排名
  const { rank, total } = margin;
  const hasRank = rank != null && total != null;
  el.innerHTML = `
    <div class="today-head"><span>融資${word}</span><b>${margin.date}</b></div>
    <div class="today-value ${dir}">${fmtSignedMinus(margin.change)}<small>億元</small></div>
    <table>
      <thead><tr>${hasRank ? `<th>${word}排名</th>` : ""}<th>融資餘額</th></tr></thead>
      <tbody><tr>
        ${hasRank ? `<td>${todayRankCell(rank, total)}</td>` : ""}
        <td><span class="today-rank">${fmt2(margin.balance)}</span> <span class="today-total">億元</span></td>
      </tr></tbody>
    </table>`;
}

// 上市大盤融資維持率（%，以 TWSE 各股融資餘額 × 收盤價自行估算）
function renderTodayMaintenance(maint: TodayMaintenance | null | undefined) {
  const el = byId("today-maintenance");
  if (!maint) {
    el.style.display = "none";
    return;
  }
  el.style.display = "";
  const change = maint.change;
  const dir = change == null ? "" : change > 0 ? "gain" : change < 0 ? "drop" : "";
  el.dataset.color = dir;
  el.innerHTML = `
    <div class="today-head"><span>上市融資維持率</span><b>${maint.date}</b></div>
    <div class="today-value">${fmt2(maint.ratio)}<small>%</small></div>
    <table>
      <thead><tr><th>較前一交易日</th></tr></thead>
      <tbody><tr>
        <td>${
          change == null
            ? `<span class="today-total">—</span>`
            : `<span class="today-rank ${dir}">${fmtSignedMinus(change)}</span> <span class="today-total">個百分點</span>`
        }</td>
      </tr></tbody>
    </table>
    <div class="today-note">依各股融資餘額 × 收盤價 ÷ 融資金額估算</div>`;
}

// ── 外資／投信每年買賣超 ──
type YearlyKind = "foreign" | "trust";
const YEARLY_NAMES: Record<YearlyKind, string> = { foreign: "外資", trust: "投信" };
const _yearlyCharts: Partial<Record<YearlyKind, echarts.ECharts>> = {};

const yearlyRows = (kind: YearlyKind) => (_data ? _data[`${kind}_yearly`] : undefined);

function renderYearlyTable(kind: YearlyKind, rows: InstitutionYear[] | undefined) {
  const tbody = byId(`t-${kind}-yearly`);
  if (!rows || !rows.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="loading">無${YEARLY_NAMES[kind]}資料</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .slice()
    .reverse()
    .map((r) => {
      const cls = r.net < 0 ? "drop" : "gain";
      return `<tr>
        <td class="left date">${r.year}</td>
        <td class="${cls}">${r.net > 0 ? "+" : ""}${fmt(r.net)}</td>
        <td>${r.buy_days}</td>
        <td>${r.sell_days}</td>
      </tr>`;
    })
    .join("");
}

function renderYearlyChart(kind: YearlyKind) {
  const rows = yearlyRows(kind);
  if (!rows || !rows.length) return;
  const T = chartTheme();
  let chart = _yearlyCharts[kind];
  if (!chart) {
    const c = echarts.init(byId(`${kind}-yearly-chart`));
    chart = c;
    _yearlyCharts[kind] = c;
    window.addEventListener("resize", () => c.resize());
  } else {
    chart.resize();
  }
  const name = YEARLY_NAMES[kind];
  chart.setOption(
    {
      backgroundColor: "transparent",
      textStyle: { color: T.ink2 },
      grid: { left: 64, right: 16, top: 20, bottom: 32 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: T.bg,
        borderColor: T.rule,
        textStyle: { color: T.ink },
        formatter: (ps: TooltipComponentFormatterCallbackParams) => {
          const r = rows[(ps as CallbackDataParams[])[0].dataIndex];
          const word = r.net < 0 ? "賣超" : "買超";
          return `${r.year}<br>${name}${word} <b>${fmt(Math.abs(r.net))}</b> 億<br>
            買超 ${r.buy_days} 天 · 賣超 ${r.sell_days} 天`;
        },
      },
      xAxis: {
        type: "category",
        data: rows.map((r) => String(r.year)),
        axisLine: { lineStyle: { color: T.ruleStrong } },
        axisLabel: { color: T.ink3 },
      },
      yAxis: {
        type: "value",
        name: "億元",
        nameTextStyle: { color: T.ink3 },
        axisLabel: { color: T.ink3 },
        splitLine: { lineStyle: { color: T.grid } },
      },
      series: [
        {
          type: "bar",
          data: rows.map((r) => ({
            value: r.net,
            itemStyle: { color: r.net < 0 ? T.down : T.up },
          })),
        },
      ],
    },
    true,
  );
}

const YEARLY_KINDS: YearlyKind[] = ["foreign", "trust"];
const currentYearlyKind = () => YEARLY_KINDS.find((k) => currentType === `${k}-yearly`);

window.addEventListener("themechange", () => {
  const kind = currentYearlyKind();
  if (kind) renderYearlyChart(kind);
});

function renderToday(data: TaiexData) {
  const ok = renderTodayIndex(data.today);
  renderTodayInstitution("today-foreign", "外資", "foreign_net", data.today_foreign);
  renderTodayInstitution("today-trust", "投信", "trust_net", data.today_trust);
  renderTodayMargin(data.today_margin && data.today_margin.margin);
  renderTodayMaintenance(data.today_margin && data.today_margin.maintenance);
  byId("today").classList.toggle("ready", ok);
}

async function fetchData() {
  try {
    const res = await fetch("data/data.json");
    const data: TaiexData = await res.json();
    const err = byId("error-banner");
    if (data.error) {
      err.style.display = "block";
      err.textContent = "資料更新失敗：" + data.error;
      return;
    }
    err.style.display = "none";
    byId("last-updated").textContent = data.last_updated || "—";

    _data = data;
    if (data.data_start) {
      const allBtn = document.querySelector('.period-btn[data-period="all"]');
      if (allBtn) allBtn.textContent = `全時（${data.data_start}～）`;
    }
    if (data.foreign_data_start) {
      query("#panel-foreign-sells-all h2").textContent =
        `歷史全時（${data.foreign_data_start}～）外資賣超前 10 名`;
      query("#panel-foreign-buys-all h2").textContent =
        `歷史全時（${data.foreign_data_start}～）外資買超前 10 名`;
    }
    if (data.trust_data_start) {
      query("#panel-trust-sells-all h2").textContent =
        `歷史全時（${data.trust_data_start}～）投信賣超前 10 名`;
      query("#panel-trust-buys-all h2").textContent =
        `歷史全時（${data.trust_data_start}～）投信買超前 10 名`;
    }
    if (data.margin_data_start) {
      [
        ["increases", "增加"],
        ["decreases", "減少"],
      ].forEach(([kind, word]) => {
        query(`#panel-margin-${kind}-all h2`).textContent =
          `歷史全時（${data.margin_data_start}～）融資${word}前 10 名`;
      });
    }
    Object.keys(STATS_PANELS).forEach((key) => {
      renderStatsPanel(key, STATS_PANELS[key].getStats(data));
    });
    renderToday(data);
    renderStreaks(data.streaks);
    YEARLY_KINDS.forEach((k) => renderYearlyTable(k, data[`${k}_yearly`]));
    const yearlyKind = currentYearlyKind();
    if (yearlyKind) renderYearlyChart(yearlyKind);
    Object.entries(TABLE_CONFIG).forEach(([id, cfg]) => {
      renderTable(
        id,
        sortedRows(data[cfg.key], _sortState[id] || "original"),
        cfg.fn,
        cfg.cls,
        cfg.cols,
      );
    });
  } catch (e) {
    console.error(e);
  }
}

// 不分期間的分頁：隱藏期間與欄位切換列
const NO_PERIOD_TYPES = new Set(["stats", "foreign-yearly", "trust-yearly"]);

function switchPanel() {
  const target = NO_PERIOD_TYPES.has(currentType)
    ? `panel-${currentType}`
    : `panel-${currentType}-${currentPeriod}`;
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  byId(target).classList.add("active");
  // K 線面板是各分頁共用的，切換分頁時關掉，避免留著上一個分頁點開的圖
  closeDropChart();
  // 圖表要在面板顯示後才初始化，隱藏時 ECharts 量不到尺寸
  const kind = currentYearlyKind();
  if (kind) renderYearlyChart(kind);
}

document.querySelectorAll<HTMLElement>(".type-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".type-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentType = btn.dataset.type!;
    const noPeriod = NO_PERIOD_TYPES.has(currentType);
    byId("period-row").style.display = noPeriod ? "none" : "";
    byId("col-toggle-bar").style.display = noPeriod ? "none" : "";
    switchPanel();
  });
});

document.querySelectorAll<HTMLElement>(".period-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentPeriod = btn.dataset.period!;
    switchPanel();
  });
});

async function hourlyRefresh() {
  await fetchData();
  setTimeout(hourlyRefresh, REFRESH_MS);
}

fetchData();
setTimeout(hourlyRefresh, REFRESH_MS);

// ── 欄位 toggle ──
const COL_TOGGLES = [
  { cls: "col-close", label: "收盤指數", on: false },
  { cls: "col-prev", label: "前日收盤", on: false },
  { cls: "col-pct", label: "漲跌幅%", on: true },
  { cls: "recovery", label: "回升／回落天數", on: true },
  { cls: "col-event", label: "事件", on: false },
];
(function initColToggles() {
  const bar = byId("col-toggle-bar");
  COL_TOGGLES.forEach((t) => {
    if (!t.on) document.body.classList.add("hide-" + t.cls);
    const btn = document.createElement("button");
    btn.className = "col-chip" + (t.on ? " on" : "");
    btn.textContent = t.label;
    btn.addEventListener("click", () => {
      const nowOn = btn.classList.toggle("on");
      document.body.classList.toggle("hide-" + t.cls, !nowOn);
    });
    bar.appendChild(btn);
  });
})();

// 匯出 PNG 用：把卡片撐到表格完整寬度（依目前勾選的欄位）
function fitExportWidth(el: HTMLElement) {
  const tables = el.querySelectorAll("table");
  let fullW;
  if (tables.length > 1) {
    // 並排多表格（如連續漲跌卡片）：讓每個表格依自身內容寬度顯示，
    // 否則 flex:1 會平分寬度，寬的表格會被裁掉右側欄位
    let sum = 0;
    tables.forEach((t) => {
      const w = t.scrollWidth;
      const flexItem = t.closest(".table-wrap")?.parentElement;
      if (flexItem) {
        flexItem.style.flex = "none";
        flexItem.style.width = w + "px";
      }
      sum += w;
    });
    fullW = sum + 60;
  } else {
    fullW = (tables[0] ? tables[0].scrollWidth : el.scrollWidth) + 40;
  }
  el.style.width = fullW + "px";
}

// ── 排序按鈕（僅套用在有對應 TABLE_CONFIG 的排行表格）與匯出 PNG 按鈕 ──
document.querySelectorAll<HTMLElement>(".card-header").forEach((header) => {
  const card = header.closest<HTMLElement>(".card")!;
  const tbodyId = card.querySelector("tbody")?.id ?? "";

  if (TABLE_CONFIG[tbodyId]) {
    _sortState[tbodyId] = "original";

    const sortBtn = document.createElement("button");
    sortBtn.className = "sort-btn";
    sortBtn.textContent = SORT_LABELS.original;
    sortBtn.addEventListener("click", () => {
      const cur = _sortState[tbodyId];
      const next = SORT_MODES[(SORT_MODES.indexOf(cur) + 1) % SORT_MODES.length];
      _sortState[tbodyId] = next;
      sortBtn.textContent = SORT_LABELS[next];
      if (_data) {
        const cfg = TABLE_CONFIG[tbodyId];
        renderTable(tbodyId, sortedRows(_data[cfg.key], next), cfg.fn, cfg.cls, cfg.cols);
      }
    });
    header.appendChild(sortBtn);
  }

  const btn = document.createElement("button");
  btn.className = "export-btn";
  btn.textContent = "⬇ PNG";
  btn.addEventListener("click", () => {
    const title = query("h2", card).textContent!.trim();
    exportPng(card, `TAIEX_${title}.png`, fitExportWidth);
  });
  header.appendChild(btn);
});

function exportPng(src: HTMLElement, filename: string, fit: (el: HTMLElement) => void) {
  // 複製一份到畫面外撐寬、截圖，原本畫面上的元素完全不受影響（不會閃一下）
  const clone = src.cloneNode(true) as HTMLElement;
  clone.classList.add("exporting");
  clone.style.position = "fixed";
  clone.style.top = "-99999px";
  clone.style.left = "0";
  clone.style.overflow = "visible";
  document.body.appendChild(clone);

  html2canvas(clone, {
    scale: 4,
    backgroundColor: chartTheme().bg,
    // html2canvas 會在這個寬度的 iframe 裡重排版，固定 1280 讓手機也套用桌面版 CSS
    windowWidth: 1280,
    // clone 是 position:fixed，與捲動位置無關；固定 scroll 為 0，避免 iOS
    // 在 iframe 內 scrollTo 失敗造成截圖範圍位移
    scrollX: 0,
    scrollY: 0,
    // 寬度要在 iframe（桌面版 CSS）裡量，不能在原頁面量：手機原頁面套的是
    // 手機版 CSS，量出的尺寸與實際截圖時的排版不同，會截不完整。
    // 不傳 width/height，html2canvas 會在 onclone 之後依 clone 的實際範圍截圖
    onclone: (_doc, el) => fit(el),
  })
    .then((canvas) => {
      document.body.removeChild(clone);
      const a = document.createElement("a");
      a.download = filename;
      a.href = canvas.toDataURL("image/png");
      a.click();
    })
    .catch((err) => {
      document.body.removeChild(clone);
      console.error(err);
    });
}

// ── K 線圖（跌幅/跌點/漲幅/漲點/外資賣超點擊） ──
let _dropChart: echarts.ECharts | null = null;
let _activeDropRow: HTMLElement | null = null;

document.addEventListener("click", (e) => {
  const tr = (e.target as Element).closest<HTMLElement>("tr.clickable-drop");
  if (!tr) return;
  const r: DayRecord = JSON.parse(decodeURIComponent(tr.dataset.drop!));
  if (_activeDropRow) _activeDropRow.classList.remove("active");
  _activeDropRow = tr;
  tr.classList.add("active");
  openDropChart(r);
});

let _bears: Bear[] | null = null;
async function loadBears(): Promise<Bear[]> {
  if (_bears) return _bears;
  const resp = await fetch("data/bear.json");
  const data: BearData = await resp.json();
  if (data.error) throw new Error(data.error);
  _bears = data.bears || [];
  return _bears;
}

function closeDropChart() {
  byId("chart-outer").style.display = "none";
  if (_activeDropRow) {
    _activeDropRow.classList.remove("active");
    _activeDropRow = null;
  }
}

function openDropChart(r: DayRecord) {
  const outer = byId("chart-outer");
  outer.style.display = "block";
  const isGain = "fallback_days" in r;
  byId("legend-day-dot").className = "legend-dot " + (isGain ? "up" : "down");
  byId("legend-day").textContent = isGain ? "大漲當日" : "跌幅當日";
  byId("legend-after-dot").className = "legend-dot " + (isGain ? "down" : "up");
  byId("legend-after").textContent = isGain ? "回落期間" : "回升期間";
  byId("chart-info").textContent =
    `${r.date}  ${r.change_pct < 0 ? "跌幅" : "漲幅"} ${r.change_pct.toFixed(2)}%  ` +
    (r.foreign_net != null ? `外資 ${fmt(r.foreign_net)} 億  ` : "") +
    (r.trust_net != null ? `投信 ${fmt(r.trust_net)} 億  ` : "") +
    (r.margin_change != null
      ? `融資 ${r.margin_change > 0 ? "+" : ""}${fmt(r.margin_change)} 億  `
      : "") +
    `前收 ${fmt(r.prev_close)} → 收 ${fmt(r.close)}` +
    (r.event ? `  ｜${r.event}` : "");
  const loading = byId("chart-loading");
  loading.style.display = "block";
  byId("chart-container").style.display = "none";
  Promise.all([loadOhlc(), loadBears()])
    .then(([ohlc, bears]) => {
      // 載入期間已切換分頁（面板被關掉）就不畫
      if (outer.style.display === "none") return;
      loading.style.display = "none";
      byId("chart-container").style.display = "block";
      renderDropChart(r, ohlc, bears);
      outer.scrollIntoView({ behavior: "smooth", block: "nearest" });
    })
    .catch((err: Error) => {
      loading.textContent = "K 線載入失敗：" + err.message;
    });
}

let _lastDropChartArgs: [DayRecord, Ohlc, Bear[]] | null = null;
window.addEventListener("themechange", () => {
  if (_dropChart && _lastDropChartArgs) renderDropChart(..._lastDropChartArgs);
});

function renderDropChart(r: DayRecord, ohlc: Ohlc, bears: Bear[]) {
  _lastDropChartArgs = [r, ohlc, bears];
  const T = chartTheme();
  const dates = ohlc.dates;
  const O = ohlc.open,
    H = ohlc.high,
    L = ohlc.low,
    C = ohlc.close;
  const vixRaw = ohlc.vix || [];
  const candleData = dates.map((_, i) => [O[i], C[i], L[i], H[i]]);
  const vixData = dates.map((_, i) => vixRaw[i] ?? null);

  const dropIdx = dates.indexOf(r.date);
  if (dropIdx < 0) return;

  // 大跌日找回升日（第一個 close >= prev_close）；大漲日找回落日（第一個 close <= prev_close）
  const isGain = "fallback_days" in r;
  let recoveryDate: string | null = null;
  for (let i = dropIdx + 1; i < dates.length; i++) {
    if (isGain ? C[i] <= r.prev_close : C[i] >= r.prev_close) {
      recoveryDate = dates[i];
      break;
    }
  }
  const nextDate = dates[dropIdx + 1] || null;

  // markArea：空頭區間底色（先畫，讓當日跌幅／回升標記疊在上層）
  const markData: MarkAreaPair[] = (bears || []).map((b) => [
    { xAxis: b.peak_date, itemStyle: { color: T.accentSoft } },
    { xAxis: b.recovery_date || b.trough_date },
  ]);
  markData.push([
    { xAxis: r.date, itemStyle: { color: isGain ? T.upLine : T.downLine } },
    { xAxis: nextDate || r.date },
  ]);
  if (recoveryDate && nextDate) {
    markData.push([
      { xAxis: nextDate, itemStyle: { color: isGain ? T.downSoft : T.upSoft } },
      { xAxis: recoveryDate },
    ]);
  }

  // 縮放範圍
  const bufPre = 60,
    bufPost = 60;
  const startI = Math.max(0, dropIdx - bufPre);
  const recIdx = recoveryDate ? dates.indexOf(recoveryDate) : -1;
  const endI =
    recIdx >= 0
      ? Math.min(dates.length - 1, recIdx + bufPost)
      : Math.min(dates.length - 1, dropIdx + 250);
  const zoomS = (startI / dates.length) * 100;
  const zoomE = (endI / dates.length) * 100;

  const option: KlineOption = {
    animation: false,
    backgroundColor: T.bg,
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: "7%", right: "3%", top: "6%", bottom: "42%" },
      { left: "7%", right: "3%", top: "66%", bottom: "12%" },
    ],
    xAxis: [
      {
        type: "category",
        data: dates,
        boundaryGap: true,
        gridIndex: 0,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: T.rule } },
        axisTick: { show: false },
      },
      {
        type: "category",
        data: dates,
        boundaryGap: true,
        gridIndex: 1,
        axisLabel: {
          formatter: (v: string) => v.slice(0, 7),
          fontSize: 10,
          rotate: 30,
          color: T.ink3,
        },
        axisLine: { lineStyle: { color: T.rule } },
        axisTick: { lineStyle: { color: T.rule } },
      },
    ],
    yAxis: [
      {
        type: "value",
        scale: true,
        gridIndex: 0,
        splitLine: { lineStyle: { color: T.rule } },
        axisLabel: {
          formatter: (v: number) => v.toLocaleString(),
          fontSize: 11,
          color: T.ink3,
        },
      },
      {
        type: "value",
        scale: true,
        gridIndex: 1,
        splitLine: { lineStyle: { color: T.grid } },
        axisLabel: { fontSize: 10, color: T.ink3 },
        name: "VIX",
        nameTextStyle: { color: T.warn, fontSize: 10 },
      },
    ],
    series: [
      {
        type: "candlestick",
        data: candleData,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: T.candleUp,
          color0: T.candleDown,
          borderColor: T.candleUp,
          borderColor0: T.candleDown,
          borderWidth: 1,
        },
        markArea: { silent: true, data: markData },
      },
      {
        type: "line",
        name: "VIX",
        data: vixData,
        xAxisIndex: 1,
        yAxisIndex: 1,
        symbol: "none",
        lineStyle: { color: T.warn, width: 1.5 },
        areaStyle: { color: T.warnSoft },
        connectNulls: false,
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: {
            color: T.warn,
            type: "dashed",
            width: 1,
            opacity: 0.4,
          },
          label: { fontSize: 11, color: T.warn, position: "end" },
          data: [
            { yAxis: 30, name: "30" },
            { yAxis: 40, name: "40" },
          ],
        },
      },
    ],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", crossStyle: { color: T.ink3 } },
      backgroundColor: T.bg,
      borderColor: T.rule,
      textStyle: { color: T.ink, fontSize: 13 },
      position(point, _params, dom, _rect, size) {
        const [px] = point;
        const [cw, ch] = size.viewSize;
        const dw = (dom as HTMLElement).offsetWidth || 100;
        const x = px + dw + 16 > cw ? px - dw - 8 : px + 12;
        return [x, ch * 0.08];
      },
      formatter(params) {
        const list = params as CallbackDataParams[];
        const p = list.find((x) => x.seriesType === "candlestick");
        const v = list.find((x) => x.seriesName === "VIX");
        if (!p) return "";
        const [o, c] = p.value as number[];
        const cc = c >= o ? T.candleUp : T.candleDown;
        const vix = v?.value as number | null | undefined;
        const vStr =
          vix != null ? `<br/><span style="color:${T.warn}">VIX ${vix.toFixed(1)}</span>` : "";
        const ev = (ohlc.events || {})[p.name];
        const evStr = ev ? `<br/><span style="color:${T.event};font-weight:600">${ev}</span>` : "";
        return `<span style="color:${T.ink3};font-size:12px">${p.name}</span><br/><span style="color:${cc}">${c.toFixed(2)}</span>${vStr}${evStr}`;
      },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: zoomS, end: zoomE },
      {
        type: "slider",
        xAxisIndex: [0, 1],
        bottom: "3%",
        height: 20,
        start: zoomS,
        end: zoomE,
        borderColor: T.rule,
        fillerColor: isGain ? T.upSoft : T.downSoft,
        handleStyle: { color: isGain ? T.up : T.down },
        textStyle: { fontSize: 10, color: T.ink3 },
      },
    ],
  };

  // 事件帶（K 線與 VIX 之間，見 kline-events.ts）；會調整 grid 版面
  const container = byId("chart-container");
  const eventItems = addEventBand(option, T, ohlc, dates, C, r.date, container.clientHeight);

  if (!_dropChart) {
    const chart = echarts.init(container);
    _dropChart = chart;
    window.addEventListener("resize", () => chart.resize());
  }
  _dropChart.setOption(option, true);
  _dropChart.resize();
  layoutEventLabels(_dropChart, eventItems);
}

// HTML 裡的 onclick 會呼叫這些函式，模組內的函式預設不是全域的
Object.assign(window, { closeStatsDetail, closeDropChart });
