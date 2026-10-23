/* K 線資料載入（index.html / bear.html 共用） */
import type { Ohlc, OhlcFile } from "./types";

/* ohlc.json 的 dates 為相對 epochStr（YYYY-MM-DD）的整數天數偏移，還原成 YYYY-MM-DD 字串 */
export function offsetsToISODates(epochStr: string, offsets: number[]): string[] {
  const [y, m, d] = epochStr.split("-").map(Number);
  const epoch = Date.UTC(y, m - 1, d);
  const DAY_MS = 86400000;
  return offsets.map((o) => new Date(epoch + o * DAY_MS).toISOString().slice(0, 10));
}

let _ohlc: Ohlc | null = null;

export async function loadOhlc(): Promise<Ohlc> {
  if (_ohlc) return _ohlc;
  const resp = await fetch("data/ohlc.json");
  const data: OhlcFile = await resp.json();
  if (data.error) throw new Error(data.error);
  const dates =
    data.date_epoch && typeof data.dates[0] === "number"
      ? offsetsToISODates(data.date_epoch, data.dates as number[])
      : (data.dates as string[]);
  _ohlc = { ...data, dates };
  return _ohlc;
}
