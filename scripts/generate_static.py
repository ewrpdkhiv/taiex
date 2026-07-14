"""
產生靜態 JSON 資料檔，供 GitHub Pages 前端使用。
輸出位置：docs/data/
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from dca import run_all as dca_run_all
from taiex_big_drops import (
    KNOWN_EVENTS,
    calculate_daily_returns,
    find_bear_markets,
    find_top_drops,
    find_top_gains,
    find_top_point_drops,
    find_top_point_gains,
    load_from_yfinance,
    load_ohlc_from_yfinance,
    load_vix_from_yfinance,
)

_TW = timezone(timedelta(hours=8))
OUT_DIR = Path(__file__).parent.parent / "docs" / "data"

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

    out = OUT_DIR / "data.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"✅ 寫出 {out}")


def generate_dca() -> None:
    print("=== 產生 DCA 回測資料 ===")
    payload = {
        "results_10y":       dca_run_all(monthly_amount=3_000, years=10),
        "results_5y":        dca_run_all(monthly_amount=3_000, years=5),
        "results_crash_10y": dca_run_all(monthly_amount=3_000, years=10, force_end=_CRASH_DATE),
        "results_crash_5y":  dca_run_all(monthly_amount=3_000, years=5,  force_end=_CRASH_DATE),
        "results_covid":     dca_run_all(monthly_amount=3_000, years=10, force_start=_COVID_START),
        "last_updated": datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S"),
        "error": None,
    }
    out = OUT_DIR / "dca.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"✅ 寫出 {out}")


def generate_bear() -> None:
    print("=== 產生空頭市場 + OHLC 資料 ===")
    ohlc_df = load_ohlc_from_yfinance()
    bears = find_bear_markets(ohlc_df[["Date", "Close"]].copy())

    clean = ohlc_df.dropna(subset=["Open", "High", "Low", "Close"])
    dates = clean["Date"].dt.strftime("%Y-%m-%d").tolist()
    vix_dict = load_vix_from_yfinance()

    now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")

    (OUT_DIR / "bear.json").write_text(
        json.dumps({"bears": bears, "last_updated": now, "error": None},
                   ensure_ascii=False, separators=(",", ":"))
    )
    print(f"✅ 寫出 {OUT_DIR / 'bear.json'}")

    (OUT_DIR / "ohlc.json").write_text(
        json.dumps({
            "dates": dates,
            "open":  clean["Open"].round(2).tolist(),
            "high":  clean["High"].round(2).tolist(),
            "low":   clean["Low"].round(2).tolist(),
            "close": clean["Close"].round(2).tolist(),
            "vix":   [vix_dict.get(d) for d in dates],
            "last_updated": now,
            "error": None,
        }, ensure_ascii=False, separators=(",", ":"))
    )
    print(f"✅ 寫出 {OUT_DIR / 'ohlc.json'}")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    for fn in (generate_data, generate_dca, generate_bear):
        try:
            fn()
        except Exception as exc:
            print(f"❌ {fn.__name__} 失敗：{exc}")
            errors.append(exc)
    if errors:
        sys.exit(1)
    print("=== 全部完成 ===")
