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
    KNOWN_EVENTS,
    analyze_bear_market_distance,
    analyze_ma_touch_returns,
    analyze_post_drop_returns,
    calculate_daily_returns,
    find_bear_markets,
    find_longest_streaks,
    find_top_drops,
    find_top_gains,
    find_top_point_drops,
    find_top_point_gains,
    load_from_yfinance,
    load_ohlc_from_yfinance,
    load_vix_from_yfinance,
    patch_missing_trading_days,
)

_TW = timezone(timedelta(hours=8))
OUT_DIR = Path(__file__).parent.parent / "docs" / "data"

_OHLC_DATE_EPOCH = "1990-01-01"
_CRASH_DATE = pd.Timestamp("2025-04-09")
_COVID_START = pd.Timestamp("2020-02-01")


def _recovery_days(drop_date: pd.Timestamp, prev_close: float, full_df: pd.DataFrame) -> int | None:
    future = full_df[full_df["Date"] > drop_date]
    recovered = future[future["Close"] >= prev_close]
    if recovered.empty:
        return None
    recovery_date = pd.Timestamp(recovered.iloc[0]["Date"])
    return int(((full_df["Date"] > drop_date) & (full_df["Date"] <= recovery_date)).sum())


def _df_to_records(df: pd.DataFrame, full_df: pd.DataFrame | None = None) -> list[dict]:
    records = []
    has_pt = "change_pt" in df.columns
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        date_str = pd.Timestamp(row["Date"]).strftime("%Y-%m-%d")
        records.append({
            "rank": rank,
            "date": date_str,
            "close": round(float(row["Close"]), 2),
            "prev_close": round(float(row["prev_close"]), 2),
            "change_pct": round(float(row["change_pct"]), 2),
            "change_pt": round(float(row["change_pt"]), 2) if has_pt else None,
            "event": KNOWN_EVENTS.get(date_str, ""),
            "recovery_days": (
                _recovery_days(pd.Timestamp(row["Date"]), float(row["prev_close"]), full_df)
                if full_df is not None else None
            ),
        })
    return records


def generate_data() -> None:
    print("=== 產生漲跌排行資料 ===")
    df = load_from_yfinance()
    df = patch_missing_trading_days(df)
    df = calculate_daily_returns(df)

    batches = [
        ("drops_20y",    find_top_drops(df,       top_n=10, years=20), True),
        ("drops_10y",    find_top_drops(df,       top_n=10, years=10), True),
        ("drops_5y",     find_top_drops(df,       top_n=10, years=5),  True),
        ("drops_all",    find_top_drops(df,       top_n=10),           True),
        ("gains_20y",    find_top_gains(df,       top_n=10, years=20), False),
        ("gains_10y",    find_top_gains(df,       top_n=10, years=10), False),
        ("gains_5y",     find_top_gains(df,       top_n=10, years=5),  False),
        ("gains_all",    find_top_gains(df,       top_n=10),           False),
        ("drops_pt_20y", find_top_point_drops(df, top_n=10, years=20), True),
        ("drops_pt_10y", find_top_point_drops(df, top_n=10, years=10), True),
        ("drops_pt_5y",  find_top_point_drops(df, top_n=10, years=5),  True),
        ("drops_pt_all", find_top_point_drops(df, top_n=10),           True),
        ("gains_pt_20y", find_top_point_gains(df, top_n=10, years=20), False),
        ("gains_pt_10y", find_top_point_gains(df, top_n=10, years=10), False),
        ("gains_pt_5y",  find_top_point_gains(df, top_n=10, years=5),  False),
        ("gains_pt_all", find_top_point_gains(df, top_n=10),           False),
    ]

    payload: dict = {"last_updated": datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S"), "error": None}
    for key, result_df, include_recovery in batches:
        payload[key] = _df_to_records(result_df, df if include_recovery else None)
    payload["post_drop_stats"] = analyze_post_drop_returns(df)
    payload["ma_touch_stats"] = {
        "ma120": analyze_ma_touch_returns(df, ma_window=120),
        "ma240": analyze_ma_touch_returns(df, ma_window=240),
    }
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
    bears = find_bear_markets(ohlc_df[["Date", "Close"]].copy())
    distance_to_bear = analyze_bear_market_distance(ohlc_df[["Date", "Close"]].copy())

    clean = ohlc_df.dropna(subset=["Open", "High", "Low", "Close"])
    dates = clean["Date"].dt.strftime("%Y-%m-%d").tolist()
    vix_dict = load_vix_from_yfinance()

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
            "events": KNOWN_EVENTS,
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
