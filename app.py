import os
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd
from flask import Flask, jsonify, render_template

_TW = timezone(timedelta(hours=8))

from taiex_big_drops import (
    KNOWN_EVENTS,
    calculate_daily_returns,
    find_top_drops,
    find_top_gains,
    find_top_point_drops,
    find_top_point_gains,
    load_from_yfinance,
)

app = Flask(__name__)

_cache: dict = {
    "drops_20y": [], "drops_10y": [], "drops_all": [],
    "gains_20y": [], "gains_10y": [], "gains_all": [],
    "drops_pt_20y": [], "drops_pt_10y": [], "drops_pt_all": [],
    "gains_pt_20y": [], "gains_pt_10y": [], "gains_pt_all": [],
    "last_updated": None,
    "error": None,
}
_lock = threading.Lock()
_REFRESH_SECONDS = 3600


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
        drop_date = pd.Timestamp(row["Date"])
        records.append(
            {
                "rank": rank,
                "date": date_str,
                "close": round(float(row["Close"]), 2),
                "prev_close": round(float(row["prev_close"]), 2),
                "change_pct": round(float(row["change_pct"]), 2),
                "change_pt": round(float(row["change_pt"]), 2) if has_pt else None,
                "event": KNOWN_EVENTS.get(date_str, ""),
                "recovery_days": _recovery_days(drop_date, float(row["prev_close"]), full_df) if full_df is not None else None,
            }
        )
    return records


def _save_csv(records: list[dict], path: str, val_col: str) -> None:
    df = pd.DataFrame(records).rename(
        columns={
            "rank": "排名",
            "date": "日期",
            "close": "收盤指數",
            "prev_close": "前日收盤",
            "change_pct": "漲跌幅(%)",
            "change_pt": val_col,
            "event": "事件",
        }
    )
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"💾 已存：{path}")


def refresh_data() -> None:
    try:
        df = load_from_yfinance()
        df = calculate_daily_returns(df)

        batches = [
            ("drops_20y",    find_top_drops(df,        top_n=10, years=20), "top10_drops_20y.csv",    "跌幅(%)", True),
            ("drops_10y",    find_top_drops(df,        top_n=10, years=10), "top10_drops_10y.csv",    "跌幅(%)", True),
            ("drops_all",    find_top_drops(df,        top_n=10),           "top10_drops_all.csv",    "跌幅(%)", True),
            ("gains_20y",    find_top_gains(df,        top_n=10, years=20), "top10_gains_20y.csv",    "漲幅(%)", False),
            ("gains_10y",    find_top_gains(df,        top_n=10, years=10), "top10_gains_10y.csv",    "漲幅(%)", False),
            ("gains_all",    find_top_gains(df,        top_n=10),           "top10_gains_all.csv",    "漲幅(%)", False),
            ("drops_pt_20y", find_top_point_drops(df,  top_n=10, years=20), "top10_drops_pt_20y.csv", "跌點",    True),
            ("drops_pt_10y", find_top_point_drops(df,  top_n=10, years=10), "top10_drops_pt_10y.csv", "跌點",    True),
            ("drops_pt_all", find_top_point_drops(df,  top_n=10),           "top10_drops_pt_all.csv", "跌點",    True),
            ("gains_pt_20y", find_top_point_gains(df,  top_n=10, years=20), "top10_gains_pt_20y.csv", "漲點",    False),
            ("gains_pt_10y", find_top_point_gains(df,  top_n=10, years=10), "top10_gains_pt_10y.csv", "漲點",    False),
            ("gains_pt_all", find_top_point_gains(df,  top_n=10),           "top10_gains_pt_all.csv", "漲點",    False),
        ]

        new_data = {}
        for key, result_df, csv_path, val_col, include_recovery in batches:
            records = _df_to_records(result_df, df if include_recovery else None)
            _save_csv(records, csv_path, val_col)
            new_data[key] = records

        with _lock:
            _cache.update(new_data)
            _cache["last_updated"] = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
            _cache["error"] = None
    except Exception as exc:
        with _lock:
            _cache["error"] = str(exc)
        print(f"❌ 資料更新失敗：{exc}")


def _schedule_refresh() -> None:
    refresh_data()
    t = threading.Timer(_REFRESH_SECONDS, _schedule_refresh)
    t.daemon = True
    t.start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    with _lock:
        return jsonify(dict(_cache))


if __name__ == "__main__":
    _schedule_refresh()
    port = int(os.environ.get("PORT", 5000))
    from waitress import serve

    serve(app, host="0.0.0.0", port=port)
