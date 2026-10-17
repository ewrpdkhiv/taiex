"""
產生靜態 JSON 資料檔，供 GitHub Pages 前端使用。
輸出位置：docs/data/
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from dca import load_all_histories as dca_load_all_histories
from dca import run_all as dca_run_all
from dca import run_dip_buy_comparison as dca_run_dip_buy_comparison
from taiex_big_drops import (
    DRAGON_BOAT_DATES,
    EVENT_SHORT_NAMES,
    KNOWN_EVENTS,
    LUNAR_NEW_YEAR_DATES,
    MID_AUTUMN_DATES,
    analyze_bear_market_distance,
    analyze_holiday_returns,
    analyze_ma_touch_returns,
    analyze_post_drop_returns,
    analyze_post_gain_returns,
    calculate_daily_returns,
    find_bear_markets,
    find_longest_streaks,
    find_top_drops,
    find_top_foreign_net_buys,
    find_top_foreign_net_sells,
    find_top_gains,
    find_top_point_drops,
    find_top_point_gains,
    load_foreign_net,
    load_ohlc_from_yfinance,
    load_usdtwd_from_yfinance,
    load_vix_from_yfinance,
    patch_missing_trading_days,
)

_TW = timezone(timedelta(hours=8))
OUT_DIR = Path(__file__).parent.parent / "docs" / "data"

_OHLC_DATE_EPOCH = "1990-01-01"
_CRASH_DATE = pd.Timestamp("2025-04-09")
_COVID_START = pd.Timestamp("2020-02-01")


def _days_until_cross(
    event_date: pd.Timestamp, prev_close: float, full_df: pd.DataFrame, *, upward: bool,
) -> int | None:
    """event_date 之後第一個收盤「站回」（upward=True，>=）或「跌回」（upward=False，<=）
    prev_close 的交易日，回傳經過的交易日數；尚未發生則回傳 None。"""
    future = full_df[full_df["Date"] > event_date]
    crossed = future[future["Close"] >= prev_close] if upward else future[future["Close"] <= prev_close]
    if crossed.empty:
        return None
    cross_date = pd.Timestamp(crossed.iloc[0]["Date"])
    return int(((full_df["Date"] > event_date) & (full_df["Date"] <= cross_date)).sum())


def _recovery_days(drop_date: pd.Timestamp, prev_close: float, full_df: pd.DataFrame) -> int | None:
    return _days_until_cross(drop_date, prev_close, full_df, upward=True)


def _fallback_days(gain_date: pd.Timestamp, prev_close: float, full_df: pd.DataFrame) -> int | None:
    return _days_until_cross(gain_date, prev_close, full_df, upward=False)


def _df_to_records(
    df: pd.DataFrame, full_df: pd.DataFrame | None = None, kind: str = "drop",
) -> list[dict]:
    """kind="drop"：計算回升天數（recovery_days）；kind="gain"：計算回落天數（fallback_days）。"""
    records = []
    has_pt = "change_pt" in df.columns
    has_foreign = "foreign_net" in df.columns
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        date_str = pd.Timestamp(row["Date"]).strftime("%Y-%m-%d")
        recovery = None
        fallback = None
        if full_df is not None and kind == "drop":
            if row["Close"] >= row["prev_close"]:
                recovery = 0  # 當日收盤未低於前日收盤，無需回升
            else:
                recovery = _recovery_days(pd.Timestamp(row["Date"]), float(row["prev_close"]), full_df)
        elif full_df is not None and kind == "gain":
            if row["Close"] <= row["prev_close"]:
                fallback = 0  # 當日收盤未高於前日收盤，無所謂回落
            else:
                fallback = _fallback_days(pd.Timestamp(row["Date"]), float(row["prev_close"]), full_df)
        record = {
            "rank": rank,
            "date": date_str,
            "close": round(float(row["Close"]), 2),
            "prev_close": round(float(row["prev_close"]), 2),
            "change_pct": round(float(row["change_pct"]), 2),
            "change_pt": round(float(row["change_pt"]), 2) if has_pt else None,
            "event": KNOWN_EVENTS.get(date_str, ""),
            "recovery_days": recovery,
        }
        if kind == "gain":
            record["fallback_days"] = fallback
        if has_foreign:
            # 外資買賣超，單位：億元（負值為賣超）
            record["foreign_net"] = round(float(row["foreign_net"]) / 1e8, 2)
        records.append(record)
    return records


def generate_data() -> None:
    print("=== 產生漲跌排行資料 ===")
    df = load_ohlc_from_yfinance()
    df = patch_missing_trading_days(df)
    df = calculate_daily_returns(df)

    batches = [
        ("drops_20y",    find_top_drops(df,       top_n=10, years=20), "drop"),
        ("drops_10y",    find_top_drops(df,       top_n=10, years=10), "drop"),
        ("drops_5y",     find_top_drops(df,       top_n=10, years=5), "drop"),
        ("drops_all",    find_top_drops(df,       top_n=10), "drop"),
        ("gains_20y",    find_top_gains(df,       top_n=10, years=20), "gain"),
        ("gains_10y",    find_top_gains(df,       top_n=10, years=10), "gain"),
        ("gains_5y",     find_top_gains(df,       top_n=10, years=5), "gain"),
        ("gains_all",    find_top_gains(df,       top_n=10), "gain"),
        ("drops_pt_20y", find_top_point_drops(df, top_n=10, years=20), "drop"),
        ("drops_pt_10y", find_top_point_drops(df, top_n=10, years=10), "drop"),
        ("drops_pt_5y",  find_top_point_drops(df, top_n=10, years=5), "drop"),
        ("drops_pt_all", find_top_point_drops(df, top_n=10), "drop"),
        ("gains_pt_20y", find_top_point_gains(df, top_n=10, years=20), "gain"),
        ("gains_pt_10y", find_top_point_gains(df, top_n=10, years=10), "gain"),
        ("gains_pt_5y",  find_top_point_gains(df, top_n=10, years=5), "gain"),
        ("gains_pt_all", find_top_point_gains(df, top_n=10), "gain"),
    ]

    payload: dict = {"last_updated": datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S"), "error": None}
    for key, result_df, kind in batches:
        payload[key] = _df_to_records(result_df, df, kind)
    try:
        foreign_df = load_foreign_net()
        for period, years in (("20y", 20), ("10y", 10), ("5y", 5), ("all", None)):
            payload[f"foreign_sells_{period}"] = _df_to_records(
                find_top_foreign_net_sells(df, foreign_df, top_n=10, years=years), df,
            )
            payload[f"foreign_buys_{period}"] = _df_to_records(
                find_top_foreign_net_buys(df, foreign_df, top_n=10, years=years), df, "gain",
            )
        payload["foreign_data_start"] = pd.Timestamp(foreign_df["Date"].min()).strftime("%Y-%m-%d")
    except Exception as exc:  # noqa: BLE001 - 外資資料失敗不應拖垮整份 data.json
        print(f"⚠ 外資買賣超資料產生失敗：{exc}")
    payload["post_drop_stats"] = analyze_post_drop_returns(df)
    payload["post_gain_stats"] = analyze_post_gain_returns(df)
    payload["ma_touch_stats"] = {
        "ma20": analyze_ma_touch_returns(df, ma_window=20),
        "ma60": analyze_ma_touch_returns(df, ma_window=60),
        "ma120": analyze_ma_touch_returns(df, ma_window=120),
        "ma240": analyze_ma_touch_returns(df, ma_window=240),
        "ma1200": analyze_ma_touch_returns(df, ma_window=1200),
        "ma2400": analyze_ma_touch_returns(df, ma_window=2400),
    }
    payload["mid_autumn_stats"] = analyze_holiday_returns(df, MID_AUTUMN_DATES)
    payload["lunar_new_year_stats"] = analyze_holiday_returns(df, LUNAR_NEW_YEAR_DATES)
    payload["dragon_boat_stats"] = analyze_holiday_returns(df, DRAGON_BOAT_DATES)
    payload["streaks"] = find_longest_streaks(df)
    payload["data_start"] = pd.Timestamp(df["Date"].min()).strftime("%Y-%m-%d")

    out = OUT_DIR / "data.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"✅ 寫出 {out}")


def generate_dca() -> None:
    print("=== 產生 DCA 回測資料 ===")
    ticker_data = dca_load_all_histories()
    payload = {
        "results_10y":       dca_run_all(ticker_data, monthly_amount=3_000, years=10),
        "results_5y":        dca_run_all(ticker_data, monthly_amount=3_000, years=5),
        "results_crash_10y": dca_run_all(ticker_data, monthly_amount=3_000, years=10, force_end=_CRASH_DATE),
        "results_crash_5y":  dca_run_all(ticker_data, monthly_amount=3_000, years=5,  force_end=_CRASH_DATE),
        "results_covid":     dca_run_all(ticker_data, monthly_amount=3_000, years=10, force_start=_COVID_START),
        "dip_buy_comparison": dca_run_dip_buy_comparison(ticker_data, monthly_amount=3_000, years=10),
        "last_updated": datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S"),
        "error": None,
    }
    out = OUT_DIR / "dca.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"✅ 寫出 {out}")


def generate_bear() -> None:
    print("=== 產生空頭市場 + OHLC 資料 ===")
    ohlc_df = load_ohlc_from_yfinance()
    ohlc_df = patch_missing_trading_days(ohlc_df)
    bears = find_bear_markets(ohlc_df[["Date", "High", "Low", "Close"]].copy())
    distance_to_bear = analyze_bear_market_distance(ohlc_df[["Date", "High", "Low", "Close"]].copy())

    clean = ohlc_df.dropna(subset=["Open", "High", "Low", "Close"])
    dates = clean["Date"].dt.strftime("%Y-%m-%d").tolist()
    vix_dict = load_vix_from_yfinance()
    twd_dict = load_usdtwd_from_yfinance()

    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")

    (OUT_DIR / "bear.json").write_text(
        json.dumps({
            "bears": bears,
            "distance_to_bear": distance_to_bear,
            "last_updated": now,
            "error": None,
        }, ensure_ascii=False, separators=(",", ":"))
    )
    print(f"✅ 寫出 {OUT_DIR / 'bear.json'}")

    # 壓縮：日期存成相對 epoch 的整數天數偏移，OHLC 四值取整數，VIX 取 1 位小數，
    # 讓 ohlc.json（最大的靜態檔）大幅縮小；前端載入後再還原成 ISO 日期字串。
    epoch = pd.Timestamp(_OHLC_DATE_EPOCH)
    date_offsets = [(pd.Timestamp(d) - epoch).days for d in dates]

    (OUT_DIR / "ohlc.json").write_text(
        json.dumps({
            "date_epoch": _OHLC_DATE_EPOCH,
            "dates": date_offsets,
            "open":  clean["Open"].round().astype(int).tolist(),
            "high":  clean["High"].round().astype(int).tolist(),
            "low":   clean["Low"].round().astype(int).tolist(),
            "close": clean["Close"].round().astype(int).tolist(),
            "vix":   [
                round(v, 1) if (v := vix_dict.get(d)) is not None else None
                for d in dates
            ],
            # 美元兌新台幣（數字越大＝台幣越弱），取 2 位小數
            "usdtwd": [
                round(v, 2) if (v := twd_dict.get(d)) is not None else None
                for d in dates
            ],
            "events": KNOWN_EVENTS,
            "event_short": EVENT_SHORT_NAMES,
            "last_updated": now,
            "error": None,
        }, ensure_ascii=False, separators=(",", ":"))
    )
    print(f"✅ 寫出 {OUT_DIR / 'ohlc.json'}")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    total_start = time.perf_counter()
    for fn in (generate_data, generate_dca, generate_bear):
        fn_start = time.perf_counter()
        try:
            fn()
        except Exception as exc:
            print(f"❌ {fn.__name__} 失敗：{exc}")
            errors.append(exc)
        print(f"⏱  {fn.__name__} 耗時 {time.perf_counter() - fn_start:.1f} 秒")
    print(f"⏱  總耗時 {time.perf_counter() - total_start:.1f} 秒")
    if errors:
        sys.exit(1)
    print("=== 全部完成 ===")
