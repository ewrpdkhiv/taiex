import * as echarts from "echarts";
import type { DefaultLabelFormatterCallbackParams as CallbackDataParams } from "echarts";
import { byId } from "./dom";
import {
  addEventBand,
  layoutEventLabels,
  type KlineOption,
  type MarkAreaPair,
} from "./kline-events";
import { loadOhlc } from "./ohlc";
import { chartTheme } from "./theme";
import type { Bear, BearData, DistanceToBear, Ohlc } from "./types";

/* ── 資料狀態 ── */
type SortCol = keyof Bear | "idx";
let _data: Bear[] = [];
let _sortCol: SortCol = "peak_date";
let _chart: echarts.ECharts | null = null; // ECharts 實例
let _activeRow: HTMLElement | null = null;

const MAX_DROP = 80;

/* ── 格式化輔助 ── */
function fmtNum(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
// 日曆天數，滿一年時加註「約 X 年 Y 天」
function calendarDaysStr(days: number): string {
  const years = Math.floor(days / 365),
    rem = days % 365;
  let s = days.toLocaleString() + " 天";
  if (years > 0) s += `（約 ${years} 年${rem > 0 ? " " + rem + " 天" : ""}）`;
  return s;
}
function recoveryStr(days: number | null, hasNested: boolean): string {
  if (days == null) return '<span class="no-recovery">尚未回高</span>';
  return `<span class="recovery-days ${hasNested ? "long" : ""}">${calendarDaysStr(days)}</span>`;
}

/* ── 統計摘要 ── */
const RECOVERY_BUCKETS = [
  { label: "< 3 個月", max: 90 },
  { label: "3–6 個月", max: 180 },
  { label: "6–12 個月", max: 365 },
  { label: "1–2 年", max: 730 },
  { label: "> 2 年", max: Infinity },
];

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
}

function computeSummary(bears: Bear[]) {
  if (!bears.length) return null;

  const drops = bears.map((b) => b.drop_pct);
  const avgDrop = drops.reduce((a, b) => a + b, 0) / drops.length;
  const maxDrop = Math.min(...drops);

  const durations = bears.map((b) => daysBetween(b.peak_date, b.trough_date));
  const avgDuration = durations.reduce((a, b) => a + b, 0) / durations.length;

  const recovered = bears.filter(
    (b): b is Bear & { recovery_date: string } => !!b.recovery_date,
  );
  const recoveryDurations = recovered.map((b) =>
    daysBetween(b.trough_date, b.recovery_date),
  );
  const avgRecovery = recoveryDurations.length
    ? recoveryDurations.reduce((a, b) => a + b, 0) / recoveryDurations.length
    : null;
  const sortedRec = [...recoveryDurations].sort((a, b) => a - b);
  const medianRecovery = sortedRec.length
    ? sortedRec[Math.floor(sortedRec.length / 2)]
    : null;

  const hist = RECOVERY_BUCKETS.map((b) => ({
    label: b.label,
    count: 0,
  }));
  recoveryDurations.forEach((d) => {
    for (let i = 0; i < RECOVERY_BUCKETS.length; i++) {
      if (d <= RECOVERY_BUCKETS[i].max) {
        hist[i].count++;
        break;
      }
    }
  });

  return {
    count: bears.length,
    avgDrop,
    maxDrop,
    avgDuration,
    avgRecovery,
    medianRecovery,
    hist,
    notRecoveredCount: bears.length - recovered.length,
  };
}

/* ── 距離熊市 ── */
function renderDistance(d: DistanceToBear | null | undefined) {
  const badge = byId("distance-badge");
  const body = byId("distance-body");
  if (!d) {
    badge.textContent = "—";
    body.innerHTML = '<div class="placeholder">暫無資料</div>';
    return;
  }

  badge.textContent = d.is_bear_market
    ? "🐻 已進入熊市"
    : `距門檻 ${d.pct_to_bear.toFixed(2)}%`;

  body.innerHTML = `
    <div class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label">最新盤中最低（${d.as_of_date}）</div>
        <div class="stat-value">${fmtNum(d.current_low ?? d.current_close)}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">歷史盤中高點（${d.peak_date}）</div>
        <div class="stat-value">${fmtNum(d.peak_value)}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">目前拉回幅度</div>
        <div class="stat-value drop-pct">${d.current_drawdown_pct.toFixed(2)}%</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">熊市門檻（${d.bear_threshold_pct.toFixed(0)}%）</div>
        <div class="stat-value">${fmtNum(d.bear_threshold_value)}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">距門檻還差點數</div>
        <div class="stat-value">${d.is_bear_market ? "已跌破" : fmtNum(d.points_to_bear) + " 點"}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">距門檻還差百分比</div>
        <div class="stat-value">${d.is_bear_market ? "已跌破" : d.pct_to_bear.toFixed(2) + "%"}</div>
      </div>
    </div>
  `;
}

function renderSummary(bears: Bear[]) {
  const s = computeSummary(bears);
  const body = byId("summary-body");
  byId("summary-badge").textContent = s ? s.count + " 次" : "—";
  if (!s) {
    body.innerHTML = '<div class="placeholder">暫無資料</div>';
    return;
  }

  const maxHistCount = Math.max(...s.hist.map((h) => h.count), 1);
  const histHtml = s.hist
    .map((h) => {
      const w = ((h.count / maxHistCount) * 100).toFixed(1);
      return `<div class="hist-row">
        <span class="hist-label">${h.label}</span>
        <div class="hist-bar-bg"><div class="hist-bar-fill" style="width:${w}%"></div></div>
        <span class="hist-count">${h.count} 次</span>
      </div>`;
    })
    .join("");

  body.innerHTML = `
    <div class="stat-grid">
      <div class="stat-tile">
        <div class="stat-label">空頭次數</div>
        <div class="stat-value">${s.count}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">平均跌幅</div>
        <div class="stat-value drop-pct">${s.avgDrop.toFixed(2)}%</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">最大跌幅</div>
        <div class="stat-value drop-pct">${s.maxDrop.toFixed(2)}%</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">平均空頭期間（高點→低點）</div>
        <div class="stat-value">${Math.round(s.avgDuration)} 天</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">平均恢復天數（低點→回高）</div>
        <div class="stat-value">${s.avgRecovery != null ? Math.round(s.avgRecovery) + " 天" : "—"}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-label">中位數恢復天數</div>
        <div class="stat-value">${s.medianRecovery != null ? s.medianRecovery + " 天" : "—"}</div>
      </div>
    </div>
    <div class="hist-wrap">
      <div class="hist-title">低點恢復時間分布${s.notRecoveredCount ? `（另有 ${s.notRecoveredCount} 次尚未恢復，不計入分布）` : ""}</div>
      ${histHtml}
    </div>
  `;
}

/* ── 表格渲染 ── */
function renderTable() {
  const sorted = [..._data].sort((a, b) => {
    let av: string | number | null | undefined, bv: typeof av;
    if (_sortCol === "idx") {
      av = _data.indexOf(a);
      bv = _data.indexOf(b);
    } else {
      av = a[_sortCol];
      bv = b[_sortCol];
    }
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string") return String(bv).localeCompare(av);
    return Number(bv) - av;
  });

  byId("bear-tbody").innerHTML = sorted
    .map((r, i) => {
      const barW = Math.min((Math.abs(r.drop_pct) / MAX_DROP) * 100, 100).toFixed(1);
      const recoveryDate = r.recovery_date;
      return `<tr data-bear='${JSON.stringify(r)}'>
      <td class="left val-cell">${i + 1}</td>
      <td class="left date-cell">${r.peak_date}</td>
      <td class="val-cell col-peak-val">${fmtNum(r.peak_value)}</td>
      <td class="left date-cell col-trough-date">${r.trough_date}</td>
      <td class="val-cell col-trough-val">${fmtNum(r.trough_value)}</td>
      <td class="col-drop">
        <div class="bar-wrap">
          <span class="drop-pct">${r.drop_pct.toFixed(2)}%</span>
          <div class="bar-bg"><div class="bar-fill" style="width:${barW}%"></div></div>
        </div>
      </td>
      <td class="col-beardays">${calendarDaysStr(r.bear_days ?? daysBetween(r.peak_date, r.trough_date))}</td>
      <td class="col-recdays">${recoveryStr(
        r.recovery_days,
        _data.some(
          (o) =>
            o.peak_date !== r.peak_date &&
            !!recoveryDate &&
            o.peak_date > r.trough_date &&
            o.peak_date < recoveryDate,
        ),
      )}</td>
      <td class="left event-cell col-event">${r.event || ""}</td>
    </tr>`;
    })
    .join("");

  /* 欄標題 */
  document.querySelectorAll<HTMLElement>("#bear-table th").forEach((th) => {
    th.classList.remove("sorted-desc");
    if (th.dataset.col === _sortCol) th.classList.add("sorted-desc");
  });

  /* 列點擊 → 開圖 */
  document.querySelectorAll<HTMLElement>("#bear-tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      const bear: Bear = JSON.parse(tr.dataset.bear!);
      if (_activeRow) _activeRow.classList.remove("active");
      _activeRow = tr;
      tr.classList.add("active");
      openChart(bear);
    });
  });
}

document.querySelectorAll<HTMLElement>("#bear-table th").forEach((th) => {
  th.addEventListener("click", () => {
    _sortCol = th.dataset.col as SortCol;
    renderTable();
  });
});

/* ── K 線：開啟面板 ── */
function openChart(bear: Bear) {
  const panel = byId("chart-panel");
  panel.style.display = "block";

  byId("chart-info").textContent =
    `${bear.peak_date} 高點 ${fmtNum(bear.peak_value)}　→　` +
    `${bear.trough_date} 低點 ${fmtNum(bear.trough_value)}　跌幅 ${bear.drop_pct.toFixed(2)}%` +
    (bear.event ? `　｜${bear.event}` : "");

  const loading = byId("chart-loading");
  loading.style.display = "block";
  byId("chart-container").style.display = "none";

  loadOhlc()
    .then((ohlc) => {
      loading.style.display = "none";
      byId("chart-container").style.display = "block";
      renderChart(bear, ohlc);
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    })
    .catch((err: Error) => {
      loading.textContent = "K 線載入失敗：" + err.message;
    });
}

/* ── K 線：關閉面板 ── */
function closeChart() {
  byId("chart-panel").style.display = "none";
  if (_activeRow) {
    _activeRow.classList.remove("active");
    _activeRow = null;
  }
}

/* ── K 線：渲染 ECharts ── */
let _lastChartArgs: [Bear, Ohlc] | null = null;
window.addEventListener("themechange", () => {
  if (_chart && _lastChartArgs) renderChart(..._lastChartArgs);
});

function renderChart(bear: Bear, ohlc: Ohlc) {
  _lastChartArgs = [bear, ohlc];
  const T = chartTheme();
  const dates = ohlc.dates;
  const O = ohlc.open,
    H = ohlc.high,
    L = ohlc.low,
    C = ohlc.close;
  const vixRaw = ohlc.vix || [];

  /* ECharts 格式：[open, close, low, high] */
  const candleData = dates.map((_, i) => [O[i], C[i], L[i], H[i]]);
  /* VIX：null 留空（ECharts 顯示斷點） */
  const vixData = dates.map((_, i) => vixRaw[i] ?? null);

  /* 計算初始縮放範圍（高點前 3 月 ~ 回高後 3 月） */
  const peakIdx = dates.indexOf(bear.peak_date);
  const troughIdx = dates.indexOf(bear.trough_date);
  const recIdx = bear.recovery_date ? dates.indexOf(bear.recovery_date) : -1;
  const bufPre = 60; // ~3 個月交易日
  const bufPost = 60;
  const startI = Math.max(0, peakIdx - bufPre);
  const endI =
    recIdx >= 0
      ? Math.min(dates.length - 1, recIdx + bufPost)
      : Math.min(dates.length - 1, troughIdx + 250);
  const zoomS = (startI / dates.length) * 100;
  const zoomE = (endI / dates.length) * 100;

  /* markArea：空頭紅 / 回升綠 */
  const markData: MarkAreaPair[] = [
    [
      {
        xAxis: bear.peak_date,
        itemStyle: { color: T.downSoft },
      },
      { xAxis: bear.trough_date },
    ],
  ];
  if (bear.recovery_date) {
    markData.push([
      {
        xAxis: bear.trough_date,
        itemStyle: { color: T.upSoft },
      },
      { xAxis: bear.recovery_date },
    ]);
  }

  /* 回升期間內的巢狀空頭：橘色標示 + 箭頭說明 */
  const nestedMarkLineData: { xAxis: string; name: string }[] = [];
  if (bear.recovery_date) {
    for (const other of _data) {
      if (other.peak_date === bear.peak_date) continue;
      if (other.peak_date > bear.trough_date && other.peak_date < bear.recovery_date) {
        markData.push([
          {
            xAxis: other.peak_date,
            itemStyle: { color: T.nestedSoft },
          },
          { xAxis: other.trough_date },
        ]);
        const pidx = dates.indexOf(other.peak_date);
        const tidx = dates.indexOf(other.trough_date);
        if (pidx >= 0 && tidx >= 0) {
          const midDate = dates[Math.floor((pidx + tidx) / 2)];
          nestedMarkLineData.push({
            xAxis: midDate,
            name: other.event || other.peak_date.slice(0, 7),
          });
        }
      }
    }
  }

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
      ...(nestedMarkLineData.length > 0
        ? [
            {
              type: "line" as const,
              data: [],
              xAxisIndex: 0,
              yAxisIndex: 0,
              markLine: {
                silent: true,
                symbol: ["none", "arrow"],
                symbolSize: 8,
                lineStyle: {
                  color: T.nested,
                  width: 1.5,
                  type: "dashed" as const,
                },
                label: {
                  show: true,
                  position: "start" as const,
                  formatter: (p: CallbackDataParams) => p.name,
                  color: T.nestedLabel,
                  fontSize: 12,
                  fontWeight: 600,
                  backgroundColor: T.nestedLabelBg,
                  padding: [3, 8],
                  borderRadius: 4,
                  borderColor: T.nested,
                  borderWidth: 1,
                },
                data: nestedMarkLineData,
              },
            },
          ]
        : []),
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
        fillerColor: T.accentSoft,
        handleStyle: { color: T.accent },
        textStyle: { fontSize: 10, color: T.ink3 },
      },
    ],
  };

  // 事件帶（K 線與 VIX 之間，見 kline-events.ts）；會調整 grid 版面
  const container = byId("chart-container");
  const eventItems = addEventBand(option, T, ohlc, dates, C, null, container.clientHeight);

  if (!_chart) {
    const chart = echarts.init(container);
    _chart = chart;
    window.addEventListener("resize", () => chart.resize());
  }
  _chart.setOption(option, true);
  _chart.resize();
  layoutEventLabels(_chart, eventItems);
}

/* ── 欄位 toggle ── */
(function initBearToggles() {
  const COLS = [
    { cls: "col-peak-val", label: "高點", on: false },
    { cls: "col-trough-date", label: "低點日期", on: false },
    { cls: "col-trough-val", label: "低點", on: false },
    { cls: "col-drop", label: "跌幅", on: true },
    { cls: "col-beardays", label: "空頭期間", on: true },
    { cls: "col-recdays", label: "回本天數", on: true },
    { cls: "col-event", label: "事件", on: false },
  ];
  const bar = byId("bear-toggle-bar");
  COLS.forEach((t) => {
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

/* ── 初始資料載入 ── */
function loadBear() {
  fetch("data/bear.json")
    .then((r) => r.json() as Promise<BearData>)
    .then((data) => {
      byId("loading").style.display = "none";
      if (data.error) {
        const el = byId("error-msg");
        el.textContent = "載入失敗：" + data.error;
        el.style.display = "block";
        return;
      }
      byId("last-updated").textContent = data.last_updated || "—";
      _data = data.bears || [];
      byId("count-badge").textContent = _data.length + " 次";
      byId("table-wrap").style.display = "block";
      renderTable();
      renderSummary(_data);
      renderDistance(data.distance_to_bear);
    })
    .catch((err) => {
      byId("loading").style.display = "none";
      const el = byId("error-msg");
      el.textContent = "網路錯誤：" + err;
      el.style.display = "block";
    });
}

// HTML 裡的 onclick 會呼叫這些函式，模組內的函式預設不是全域的
Object.assign(window, { closeChart });

loadBear();
