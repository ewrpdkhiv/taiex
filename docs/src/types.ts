/* docs/data/*.json 的資料格式，對應 scripts/generate_static.py 的輸出。
   Python 端改了欄位，這裡要跟著改，前端才會在編譯時發現不一致。 */

export type Period = "5y" | "10y" | "20y" | "all";

/* ── data.json ── */

/* 單日排行（漲跌幅、漲跌點、外資、融資）共用欄位 */
export interface DayRecord {
  rank: number;
  date: string;
  close: number;
  prev_close: number;
  change_pct: number;
  change_pt: number;
  event: string;
  /* 跌幅類：回升天數（null = 尚未回升） */
  recovery_days?: number | null;
  /* 漲幅類：回落天數（null = 尚未回落）；有這個欄位就是漲幅類 */
  fallback_days?: number | null;
  /* 外資排行才有（億元） */
  foreign_net?: number;
  /* 投信排行才有（億元） */
  trust_net?: number;
  /* 融資排行才有（億元） */
  margin_change?: number;
  margin_balance?: number;
}

export interface ForeignRecord extends DayRecord {
  foreign_net: number;
}

export interface TrustRecord extends DayRecord {
  trust_net: number;
}

export interface MarginRecord extends DayRecord {
  margin_change: number;
  margin_balance: number;
}

type DayRankingKey = `${"drops" | "gains" | "drops_pt" | "gains_pt"}_${Period}`;
type ForeignRankingKey = `foreign_${"sells" | "buys"}_${Period}`;
type TrustRankingKey = `trust_${"sells" | "buys"}_${Period}`;
type MarginRankingKey = `margin_${"increases" | "decreases"}_${Period}`;

export type Rankings = { [K in DayRankingKey]?: DayRecord[] } & {
  [K in ForeignRankingKey]?: ForeignRecord[];
} & { [K in TrustRankingKey]?: TrustRecord[] } & { [K in MarginRankingKey]?: MarginRecord[] };

export type RankingKey = keyof Rankings;

/* 大跌／大漲／跌破均線後的個別事件 */
export interface PostEvent {
  date: string;
  return_pct: number;
  drop_pct?: number;
  gain_pct?: number;
  touch_pct?: number;
}

/* 節日連假（中秋、過年、端午）的個別事件 */
export interface HolidayEvent {
  festival_date: string;
  holiday_start: string;
  holiday_end: string;
  holiday_days: number;
  buy_date: string;
  sell_date: string;
  buy_close: number;
  sell_close: number;
  return_pct: number;
}

export interface Horizon<E = PostEvent | HolidayEvent> {
  days: number;
  avg_return_pct: number | null;
  median_return_pct: number;
  win_rate_pct: number;
  sample_size: number;
  events?: E[];
}

export interface Stats<E = PostEvent | HolidayEvent> {
  threshold?: number;
  ma_window?: number;
  sample_size: number;
  horizons: Horizon<E>[];
}

export interface Streak {
  direction: "up" | "down";
  start_date: string;
  end_date: string;
  days: number;
  cumulative_pct: number;
}

/* 外資／投信每年買賣超合計（億元） */
export interface InstitutionYear {
  year: number;
  net: number;
  buy_days: number;
  sell_days: number;
}

export interface TodayIndex {
  date: string;
  close: number;
  change_pct: number;
  change_pt: number;
  direction: "drop" | "gain" | "flat";
  ranks: { all: { pct: number; pt: number; total: number } };
}

/* 外資用 foreign_net、投信用 trust_net 欄位（億元） */
export type InstitutionKey = "foreign_net" | "trust_net";

export type TodayInstitution = {
  date: string;
  direction: "sell" | "buy" | "flat";
  ranks: { all: { rank: number; total: number } };
  streak: number;
  streak_days?: ({ date: string } & Partial<Record<InstitutionKey, number>>)[];
} & Partial<Record<InstitutionKey, number>>;

export interface TodayMargin {
  date: string;
  balance: number;
  change: number;
  /* 持平時不排名 */
  rank: number | null;
  total: number | null;
}

export interface TodayMaintenance {
  date: string;
  ratio: number;
  change: number | null;
}

export type MaWindow = "ma20" | "ma60" | "ma120" | "ma240" | "ma1200" | "ma2400";

export interface TaiexData extends Rankings {
  last_updated?: string;
  error?: string | null;
  data_start?: string;
  foreign_data_start?: string;
  trust_data_start?: string;
  margin_data_start?: string;
  post_drop_stats?: Stats<PostEvent>;
  post_gain_stats?: Stats<PostEvent>;
  ma_touch_stats?: Partial<Record<MaWindow, Stats<PostEvent>>>;
  mid_autumn_stats?: Stats<HolidayEvent>;
  lunar_new_year_stats?: Stats<HolidayEvent>;
  dragon_boat_stats?: Stats<HolidayEvent>;
  streaks?: { up?: Streak[]; down?: Streak[] };
  foreign_yearly?: InstitutionYear[];
  trust_yearly?: InstitutionYear[];
  today?: TodayIndex | null;
  today_foreign?: TodayInstitution | null;
  today_trust?: TodayInstitution | null;
  today_margin?: {
    margin: TodayMargin | null;
    maintenance: TodayMaintenance | null;
  } | null;
}

/* ── bear.json ── */

export interface Bear {
  peak_date: string;
  peak_value: number;
  trough_date: string;
  trough_value: number;
  drop_pct: number;
  bear_days?: number;
  recovery_date: string | null;
  recovery_days: number | null;
  event?: string;
}

export interface DistanceToBear {
  as_of_date: string;
  current_close: number;
  current_low?: number | null;
  peak_date: string;
  peak_value: number;
  current_drawdown_pct: number;
  bear_threshold_pct: number;
  bear_threshold_value: number;
  points_to_bear: number;
  pct_to_bear: number;
  is_bear_market: boolean;
}

export interface BearData {
  bears?: Bear[];
  distance_to_bear?: DistanceToBear | null;
  last_updated?: string;
  error?: string | null;
}

/* ── ohlc.json ── */

/* 檔案裡 dates 存成相對 date_epoch 的天數偏移，loadOhlc() 會還原成 YYYY-MM-DD */
export interface OhlcFile {
  date_epoch?: string;
  dates: (number | string)[];
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  vix?: (number | null)[];
  events?: Record<string, string>;
  event_short?: Record<string, string>;
  last_updated?: string;
  error?: string | null;
}

export interface Ohlc extends Omit<OhlcFile, "dates"> {
  dates: string[];
}

/* ── dca.json ── */

export interface DcaPerformance {
  invested?: number;
  shares: number | null;
  market_value: number | null;
  return_rate: number | null;
  irr: number | null;
  max_drawdown: number | null;
  calmar: number | null;
}

export interface DcaResult {
  ticker: string;
  name: string;
  monthly_amount: number;
  invested: number | null;
  months: number;
  start_date: string;
  end_date: string;
  last_price: number | null;
  market_cap: number | null;
  tags?: string[];
  reinvest: DcaPerformance;
}

export interface DipCompare {
  ticker: string;
  name: string;
  tags?: string[];
  dip_trigger_count: number;
  baseline: DcaPerformance;
  dip_buy: DcaPerformance;
}

export interface YearlyResult {
  ticker: string;
  name: string;
  tags?: string[];
  by_year: Record<string, { irr: number | null; return_rate: number | null; months: number } | undefined>;
}

export interface Yearly {
  years: number[];
  ytd_year: number | null;
  results: YearlyResult[];
}

export type DcaPeriod = "10y" | "5y" | "crash_10y" | "crash_5y" | "covid";

export type DcaData = { [K in DcaPeriod as `results_${K}`]?: DcaResult[] } & {
  dip_buy_comparison?: DipCompare[];
  yearly?: Yearly;
  last_updated?: string;
  error?: string | null;
};
