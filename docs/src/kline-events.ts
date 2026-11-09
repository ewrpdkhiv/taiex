/* K 線圖事件帶（index.html / bear.html 共用）：
   在 K 線區與 VIX 區之間加一條「事件帶」，事件以短名稱色塊排在帶上（最多 3 排），
   與 K 線同步縮放；放不下的事件在帶底部只畫小圓點（完整說明在 tooltip）。
   K 線區只留淡淡的虛線對位，不放文字。
   排位順序：focusDate（點開的那天）最優先，其餘依當日漲跌幅絕對值由大到小。
   縮放／拖動／視窗縮放時重新排版。 */
import type {
  DataZoomComponentOption,
  ECharts,
  EChartsOption,
  GridComponentOption,
  SeriesOption,
  XAXisComponentOption,
  YAXisComponentOption,
} from "echarts";
import type { ChartTheme } from "./theme";
import type { Ohlc } from "./types";

const ROWS = 3;
const ROW_H = 22; // 每排高度（px）
const GAP = 6; // 同排色塊最小間距（px）
const FONT_SIZE = 12;
const PAD_X = 6;
const DOT_STRIP = 10; // 帶底部放小圓點的高度
const BAND_H = DOT_STRIP + ROWS * ROW_H + 4;
const BAND_ID = "event-band";

/* K 線 option：各元件都用陣列，事件帶會往裡面加東西 */
export interface KlineOption extends EChartsOption {
  grid: GridComponentOption[];
  xAxis: XAXisComponentOption[];
  yAxis: YAXisComponentOption[];
  dataZoom: DataZoomComponentOption[];
  series: SeriesOption[];
}

/* markArea 的一段區間：[起點（含底色）, 終點] */
export type MarkAreaPair = [{ xAxis: string; itemStyle: { color: string } }, { xAxis: string }];

export interface EventItem {
  date: string;
  name: string;
  priority: number;
}

let _ctx: CanvasRenderingContext2D | null = null;
function textWidth(s: string): number {
  _ctx ??= document.createElement("canvas").getContext("2d");
  if (!_ctx) return s.length * FONT_SIZE + PAD_X * 2;
  _ctx.font = `600 ${FONT_SIZE}px "Noto Sans TC", sans-serif`;
  return _ctx.measureText(s).width + PAD_X * 2;
}

/* 把事件帶加進 K 線 option（就地修改），回傳事件項目供 layoutEventLabels 使用。
   option 需有 grid[0]（K 線）、grid[1]（VIX），dates 為 xAxis 的日期 category。
   closes = 與日期對齊的收盤價（算排位優先度用）；height = 圖表容器高度（px） */
export function addEventBand(
  option: KlineOption,
  T: ChartTheme,
  ohlc: Ohlc,
  dates: string[],
  closes: number[],
  focusDate: string | null,
  height: number,
): EventItem[] {
  const events = ohlc.events || {};
  const shorts = ohlc.event_short || {};
  const idx = new Map(dates.map((d, i) => [d, i]));
  const items = Object.keys(events)
    .filter((d) => idx.has(d))
    .map((d) => {
      const i = idx.get(d)!;
      return {
        date: d,
        name: shorts[d] || events[d],
        priority:
          d === focusDate
            ? Infinity
            : i > 0
              ? Math.abs(closes[i] / closes[i - 1] - 1)
              : 0,
      };
    });

  // 版面（px）：由下往上依序為 滑桿＋日期、VIX、事件帶、K 線
  const bottomArea = Math.round(height * 0.12);
  const vixH = Math.round(height * 0.16);
  const bandBottom = bottomArea + vixH + 10;
  const { left, right } = option.grid[0];
  option.grid[0] = { left, right, top: 16, bottom: bandBottom + BAND_H + 8 };
  option.grid[1] = { left, right, bottom: bottomArea, height: vixH };
  option.grid.push({
    left,
    right,
    bottom: bandBottom,
    height: BAND_H,
    show: true,
    backgroundColor: T.surface2,
    borderColor: T.rule,
    borderWidth: 1,
  });
  const bandAxis = option.xAxis.length;
  option.xAxis.push({
    type: "category",
    data: dates,
    gridIndex: option.grid.length - 1,
    boundaryGap: true,
    show: false,
  });
  option.yAxis.push({
    type: "value",
    gridIndex: option.grid.length - 1,
    min: 0,
    max: BAND_H,
    show: false,
  });
  option.dataZoom.forEach((z) => {
    z.xAxisIndex = option.xAxis.map((_, i) => i);
  });

  option.series.push(
    {
      // K 線區的對位虛線
      type: "line",
      data: [],
      xAxisIndex: 0,
      yAxisIndex: 0,
      markLine: {
        silent: true,
        symbol: ["none", "none"],
        label: { show: false },
        lineStyle: { color: T.event, width: 1, type: "dashed", opacity: 0.3 },
        data: items.map((it) => ({ xAxis: it.date })),
      },
    },
    {
      id: BAND_ID,
      type: "scatter",
      xAxisIndex: bandAxis,
      yAxisIndex: option.yAxis.length - 1,
      z: 5,
      tooltip: { show: false },
      itemStyle: { color: T.event },
      label: {
        formatter: (p) => p.name,
        position: "inside",
        color: T.eventLabel,
        fontSize: FONT_SIZE,
        fontWeight: 600,
        backgroundColor: T.eventLabelBg,
        padding: [3, PAD_X],
        borderRadius: 4,
      },
      data: [],
    },
  );
  return items;
}

/* ECharts 沒有公開 grid 的版面範圍，借用內部的 getModel() 與 coordinateSystem.getRect() */
interface ChartInternals {
  getModel(): {
    getComponent(type: "grid", idx: number):
      | { coordinateSystem: { getRect(): { x: number; width: number } } }
      | undefined;
  };
}

const _items = new WeakMap<ECharts, EventItem[]>();
const _hooked = new WeakSet<ECharts>();

/* 依目前縮放範圍，替每個事件分配排數並更新事件帶 */
function layout(chart: ECharts) {
  const items = _items.get(chart);
  if (!items) return;
  const grid = (chart as unknown as ChartInternals).getModel().getComponent("grid", 0);
  if (!grid) return;
  const rect = grid.coordinateSystem.getRect();
  const placed: [number, number][][] = Array.from({ length: ROWS }, () => []); // 每排已放的 [left, right]
  const data: object[] = [];
  [...items]
    .sort((a, b) => b.priority - a.priority)
    .forEach((it) => {
      const x = chart.convertToPixel({ xAxisIndex: 0 }, it.date) as number | undefined;
      if (x == null || isNaN(x) || x < rect.x || x > rect.x + rect.width) return;
      const w = textWidth(it.name);
      const left = x - w / 2;
      const right = x + w / 2;
      const row = placed.findIndex((spans) =>
        spans.every(([l, r]) => right + GAP <= l || left >= r + GAP),
      );
      if (row < 0) {
        data.push({
          name: it.name,
          value: [it.date, DOT_STRIP / 2],
          symbolSize: 5,
          label: { show: false },
        });
        return;
      }
      placed[row].push([left, right]);
      data.push({
        name: it.name,
        value: [it.date, BAND_H - 2 - ROW_H / 2 - row * ROW_H],
        symbolSize: 0,
        label: { show: true },
      });
    });
  chart.setOption({ series: [{ id: BAND_ID, data }] });
}

/* setOption 之後呼叫；第一次呼叫時掛上縮放與視窗大小改變的重新排版 */
export function layoutEventLabels(chart: ECharts, items: EventItem[]) {
  _items.set(chart, items);
  if (!_hooked.has(chart)) {
    _hooked.add(chart);
    let pending = false;
    const relayout = () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        layout(chart);
      });
    };
    chart.on("datazoom", relayout);
    window.addEventListener("resize", relayout);
  }
  layout(chart);
}
