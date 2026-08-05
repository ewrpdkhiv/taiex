"""
台股加權指數 (TAIEX) 單日跌幅 >= 5% 篩選工具
===============================================
支援兩種資料來源：
  1. yfinance（自動下載，需能連線 Yahoo Finance）
  2. CSV 手動匯入（從證交所下載後指定路徑）

用法：
  # 方法一：yfinance 自動下載
  python taiex_big_drops.py

  # 方法二：指定 CSV 檔案
  python taiex_big_drops.py --csv your_taiex_data.csv

  # 調整跌幅門檻（預設 5%）
  python taiex_big_drops.py --threshold 6

CSV 格式（從台灣證交所下載）：
  https://www.twse.com.tw/zh/indices/taiex/mi-5min-hist.html
  欄位：日期, 開盤指數, 最高指數, 最低指數, 收盤指數
"""

import argparse
import sys

import pandas as pd

# ── 常數 ──────────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLD = 5.0
TAIEX_TICKER = "^TWII"
START_DATE = "1990-01-01"
TWSE_INDEX_HIST_URL = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"

# 已知重大事件標籤（跌幅與漲幅共用）
KNOWN_EVENTS: dict[str, str] = {
    # ── 跌幅事件 ──
    "2025-04-07": "川普對等關稅（史上最大跌幅）",
    "2024-08-05": "日本升息引發全球套利平倉",
    "2024-08-02": "日圓套利平倉恐慌擴散（日銀升息後）",
    "2024-09-04": "美股半導體暴跌引發台股科技股賣壓",
    "2025-02-03": "川普宣布對中加墨加徵關稅",
    "2025-03-31": "川普「解放日」關稅前夕恐慌賣壓",
    "2025-04-09": "對等關稅正式生效",
    "2020-03-19": "COVID-19 疫情恐慌",
    "2020-03-12": "COVID-19 疫情恐慌",
    "2020-01-30": "COVID-19 疫情初期擴散恐慌",
    "2018-10-11": "美中貿易戰擔憂引發全球股災",
    "2011-08-05": "美國主權信評遭調降至 AA+",
    "2008-10-07": "金融海嘯（雷曼兄弟破產後）",
    "2008-10-08": "金融海嘯持續蔓延",
    "2008-11-06": "金融海嘯持續蔓延",
    "2008-01-22": "全球股市恐慌（法興銀行詐欺案）",
    "2004-03-22": "319 槍擊案隔日開盤",
    "2001-09-17": "911 恐攻後首個開市日",
    "2000-11-20": "科技泡沫崩潰後期",
    "2000-10-19": "科技泡沫崩潰持續",
    "2000-10-02": "科技泡沫崩潰持續",
    "2000-03-13": "科技泡沫崩潰",
    "1997-10-20": "亞洲金融風暴高峰",
    "1999-07-16": "李登輝「兩國論」引發台海危機",
    "1990-08-23": "台灣泡沫崩潰 + 波灣戰爭",
    "2026-06-08": "費城半導體崩跌 10%，博通財報展望未上修引發科技股拋售潮",
    "2026-06-04": "美伊衝突持續升溫",
    "2026-03-04": "美伊衝突升溫，油價飆升全球恐慌賣壓",
    "2026-03-09": "美伊衝突蔓延，台積電等科技權值股重挫",
    "2025-11-21": "外資單日賣超逾 900 億，創史上第六大跌點",
    "2021-05-12": "台灣本土疫情升溫，三級警戒恐慌引發股災",
    # ── 漲幅事件 ──
    "2026-05-29": "AI 攻頂行情，輝達供應鏈全面暴漲",
    "2026-05-25": "美伊達成協議、黃仁勳來台固樁、外資大舉回補三重利多",
    "2026-05-21": "AI 熱潮延續，電子權值股帶動創新高",
    "2026-05-04": "AI 題材延燒，台股站上史上新高",
    "2026-04-24": "4 月史上最強月行情延續，AI 供應鏈持續發酵",
    "2026-04-08": "美伊停戰延後兩週，川普宣布緩衝，油價暴跌，全球風險情緒回溫",
    "2026-04-04": "AI 題材持續發酵，台股史上最大單日漲點",
    "2026-04-01": "美伊停戰曙光（「荷莫茲希望」行情），漲 1,452 點創史上第二大漲點",
    "2026-03-11": "NVIDIA GTC 2026 前夕題材爆發，美伊局勢緩和，AI 供應鏈大漲",
    "2026-02-24": "AI/CPO 題材發威，外資單日買超 627 億，台積電衝新高，漲 927 點",
    "2025-04-10": "川普宣布對等關稅暫緩 90 天",
    "2020-03-20": "COVID-19 恐慌後技術性反彈",
    "2009-04-30": "金融海嘯後全球股市持續復甦反彈",
    "2008-10-30": "聯準會宣布降息救市",
    "2008-10-14": "G7 宣布協調救市行動",
    "2008-09-19": "美政府宣布 TARP 不良資產救助計畫",
    "2008-09-08": "美政府接管房利美、房地美",
    "2001-12-06": "911 後景氣回穩，外資回補",
    "2000-10-20": "科技泡沫後技術性反彈",
    "1999-02-22": "亞洲金融風暴後強勁反彈",
    "1999-02-08": "亞洲金融風暴後急速反彈",
    "1997-10-21": "亞洲金融風暴後短期反彈",
}


# ── 資料讀取 ──────────────────────────────────────────────────────────────────


def _cached_yf_download(cache_path, ticker: str, start: str, cols: list[str]) -> pd.DataFrame:
    """從快取讀取 + 增量抓取 yfinance 資料，回傳合併後、依 start 篩選的 DataFrame。"""
    import yfinance as yf  # pylint: disable=import-outside-toplevel
    from price_cache import OVERLAP_DAYS, _merge_frames, read_cache, write_cache

    cached = read_cache(cache_path)
    start_ts = pd.Timestamp(start)
    if cached is None or start_ts < cached["Date"].min():
        fetch_start = start
    else:
        fetch_start = max(
            start_ts, cached["Date"].max() - pd.Timedelta(days=OVERLAP_DAYS)
        ).strftime("%Y-%m-%d")

    raw = yf.download(ticker, start=fetch_start, progress=False, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    available_cols = [c for c in cols if c in raw.columns]
    fresh = raw[available_cols].copy()
    fresh.index.name = "Date"
    fresh = fresh.reset_index()
    fresh["Date"] = pd.to_datetime(fresh["Date"])

    combined = _merge_frames(cached, fresh)
    write_cache(cache_path, combined)
    return combined[combined["Date"] >= start_ts].reset_index(drop=True)


def load_ohlc_from_yfinance(start: str = START_DATE) -> pd.DataFrame:
    """從快取 + yfinance 增量抓取 TAIEX OHLC 資料（Date, Open, High, Low, Close）。"""
    try:
        import yfinance as yf  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import
    except ImportError as exc:
        raise ImportError("請先安裝 yfinance：pip install yfinance") from exc

    from price_cache import CACHE_DIR

    df = _cached_yf_download(
        CACHE_DIR / "index" / "TWII.csv", TAIEX_TICKER, start,
        ["Open", "High", "Low", "Close"],
    )
    if df.empty:
        raise RuntimeError("OHLC 資料下載失敗")
    return df


def load_from_yfinance(start: str = START_DATE) -> pd.DataFrame:
    """取得台股加權指數歷史資料（Date, Close），底層與 load_ohlc_from_yfinance 共用快取。

    Raises:
        ImportError: yfinance 未安裝。
        RuntimeError: 下載失敗或資料為空。
    """
    df = load_ohlc_from_yfinance(start)[["Date", "Close"]]
    if df.empty:
        raise RuntimeError("下載失敗或資料為空。請確認網路連線，或改用 --csv 模式。")
    return df


def load_vix_from_yfinance(start: str = START_DATE) -> dict[str, float]:
    """取得 VIX 收盤價（快取 + 增量抓取），回傳 {date_str: vix_close}。失敗回傳空 dict。"""
    try:
        from price_cache import CACHE_DIR

        df = _cached_yf_download(CACHE_DIR / "index" / "VIX.csv", "^VIX", start, ["Close"])
        result: dict[str, float] = {}
        for _, row in df.iterrows():
            try:
                result[pd.Timestamp(row["Date"]).strftime("%Y-%m-%d")] = round(float(row["Close"]), 2)
            except (KeyError, ValueError, TypeError):
                pass
        return result
    except Exception as e:
        print(f"⚠ VIX 下載失敗：{e}")
        return {}


def _parse_twse_month_payload(payload: dict) -> pd.DataFrame:
    """解析 TWSE「發行量加權股價指數歷史資料」API 回傳的單月 JSON。

    Args:
        payload: TWSE API（MI_5MINS_HIST）回傳的 JSON（已解析成 dict）。

    Returns:
        含 Date、Open、High、Low、Close 欄位的 DataFrame；查無資料回傳空表。
    """
    columns = ["Date", "Open", "High", "Low", "Close"]
    if payload.get("stat") != "OK" or not payload.get("data"):
        return pd.DataFrame(columns=columns)

    rows = []
    for date_str, open_str, high_str, low_str, close_str, *_ in payload["data"]:
        date = _parse_roc_or_ad_date(date_str.strip())
        if date is None:
            continue
        try:
            o, h, l, c = (
                float(v.replace(",", ""))
                for v in (open_str, high_str, low_str, close_str)
            )
        except ValueError:
            continue
        rows.append({"Date": date, "Open": o, "High": h, "Low": l, "Close": c})

    return pd.DataFrame(rows, columns=columns)


def _fetch_twse_month(year: int, month: int) -> pd.DataFrame:
    """向 TWSE 官方 API 查詢指定年月的加權股價指數日 OHLC 資料。

    網路或格式錯誤時回傳空表、不拋出例外，讓呼叫端可以逐月容錯地補資料。
    """
    import requests  # pylint: disable=import-outside-toplevel

    date_str = f"{year:04d}{month:02d}01"
    try:
        resp = requests.get(
            TWSE_INDEX_HIST_URL,
            params={"response": "json", "date": date_str},
            timeout=15,
        )
        resp.raise_for_status()
        return _parse_twse_month_payload(resp.json())
    except Exception as e:  # noqa: BLE001 - 任何查詢失敗都應該容錯繼續
        print(f"⚠ TWSE {year}-{month:02d} 資料查詢失敗：{e}")
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close"])


def patch_missing_trading_days(
    df: pd.DataFrame,
    start: str = "1999-01-01",
    end: str = "2000-12-31",
    fetch_month=_fetch_twse_month,
) -> pd.DataFrame:
    """用 TWSE 官方歷史資料，補齊 yfinance 缺漏的交易日。

    yfinance 的 ^TWII 歷史資料在 1999～2000 年左右，會漏掉部分「補行上班日」
    星期六的交易資料（例如 1999-02-20）。這會讓橫跨缺漏日的漲跌幅被誤算成
    單一交易日的跳空，實際上中間還有一個官方確實有開盤的交易日。這個函式
    逐月向 TWSE 官方 API 查詢指定期間資料，把 df 裡沒有的交易日補進去。

    Args:
        df: 含 Date（可選 Open/High/Low/Close）欄位的 DataFrame。
        start, end: 只在這個日期範圍內查詢 TWSE，避免對整段歷史做不必要的
            網路請求（此問題目前已知只發生在 2001 年以前）。
        fetch_month: 查詢單月資料的函式，預設為 _fetch_twse_month；測試時
            可替換成假資料來源，避免真的發網路請求。

    Returns:
        補上缺漏交易日後、依日期排序的新 DataFrame。
    """
    existing_dates = set(pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d"))
    months = pd.period_range(start=start, end=end, freq="M")

    missing_rows = []
    for period in months:
        month_df = fetch_month(period.year, period.month)
        if month_df.empty:
            continue
        for _, row in month_df.iterrows():
            date_str = row["Date"].strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                missing_rows.append(row)
                existing_dates.add(date_str)

    if not missing_rows:
        return df

    print(f"🩹 從 TWSE 補齊 {len(missing_rows)} 個 yfinance 缺漏的交易日")
    patched = pd.concat([df, pd.DataFrame(missing_rows)], ignore_index=True)
    return patched.sort_values("Date").reset_index(drop=True)


def load_from_csv(path: str) -> pd.DataFrame:
    """從 CSV 檔案讀取台股加權指數歷史資料。

    支援兩種格式：
      - 台灣證交所格式：日期欄位為民國年（如 114/04/07）
      - 標準格式：Date, Close（西元年）

    Args:
        path: CSV 檔案路徑。

    Returns:
        包含 Date、Close 欄位的 DataFrame。

    Raises:
        FileNotFoundError: 檔案不存在。
        ValueError: 無法解析欄位。
    """
    print(f"📂 讀取 CSV 檔案：{path}")
    raw = pd.read_csv(path, encoding="utf-8-sig")
    print(f"   原始欄位：{list(raw.columns)}")

    # 嘗試判斷欄位名稱（兼容證交所格式與一般格式）
    col_map = _detect_columns(raw)
    df = raw[[col_map["date"], col_map["close"]]].copy()
    df.columns = ["Date", "Close"]

    # 處理民國年（如 114/04/07 → 2025-04-07）
    df["Date"] = df["Date"].astype(str).apply(_parse_roc_or_ad_date)
    df = df.dropna(subset=["Date"])

    # 清理 Close（去除千分位逗號）
    df["Close"] = (
        df["Close"].astype(str).str.replace(",", "", regex=False).astype(float)
    )

    df = df.sort_values("Date").reset_index(drop=True)
    print(f"✅ 讀取完成，共 {len(df):,} 筆交易日資料")
    return df


def _detect_columns(df: pd.DataFrame) -> dict[str, str]:
    """自動偵測日期與收盤價欄位名稱。

    Args:
        df: 原始 DataFrame。

    Returns:
        含 date、close 鍵的欄位名稱對照字典。

    Raises:
        ValueError: 無法找到所需欄位。
    """
    columns_lower = {col.lower().strip(): col for col in df.columns}

    date_candidates = ["日期", "date", "年月日"]
    close_candidates = ["收盤指數", "close", "收盤", "closing index", "指數"]

    date_col = next(
        (columns_lower[k] for k in date_candidates if k in columns_lower), None
    )
    close_col = next(
        (columns_lower[k] for k in close_candidates if k in columns_lower), None
    )

    if not date_col:
        raise ValueError(
            f"找不到日期欄位，現有欄位：{list(df.columns)}\n"
            "請確認欄位名稱含有「日期」或「Date」。"
        )
    if not close_col:
        raise ValueError(
            f"找不到收盤指數欄位，現有欄位：{list(df.columns)}\n"
            "請確認欄位名稱含有「收盤指數」或「Close」。"
        )

    return {"date": date_col, "close": close_col}


def _parse_roc_or_ad_date(date_str: str) -> pd.Timestamp | None:
    """解析民國年或西元年日期字串。

    Args:
        date_str: 日期字串，如 "114/04/07" 或 "2025-04-07"。

    Returns:
        pd.Timestamp 或 None（解析失敗時）。
    """
    date_str = date_str.strip()

    # 民國年格式：114/04/07 或 114/4/7
    if "/" in date_str:
        parts = date_str.split("/")
        if len(parts) == 3:
            try:
                year = int(parts[0])
                # 民國年轉西元（民國 < 200 時視為民國年）
                if year < 200:
                    year += 1911
                return pd.Timestamp(f"{year}-{int(parts[1]):02d}-{int(parts[2]):02d}")
            except ValueError:
                return None

    # 嘗試標準 pandas 解析
    try:
        return pd.Timestamp(date_str)
    except (ValueError, TypeError):
        return None


# ── 分析核心 ──────────────────────────────────────────────────────────────────


def calculate_daily_returns(df: pd.DataFrame) -> pd.DataFrame:
    """計算每日漲跌幅。

    Args:
        df: 含 Date、Close 欄位的 DataFrame。

    Returns:
        新增 prev_close、change_pct 欄位的 DataFrame。
    """
    df = df.sort_values("Date").copy()
    df["prev_close"] = df["Close"].shift(1)
    df["change_pct"] = (df["Close"] - df["prev_close"]) / df["prev_close"] * 100
    df["change_pt"] = df["Close"] - df["prev_close"]
    return df


def find_big_drops(
    df: pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
) -> pd.DataFrame:
    """篩選單日跌幅超過門檻的交易日。

    Args:
        df: 含 change_pct 欄位的 DataFrame。
        threshold: 跌幅門檻（正數，如 5 代表 >= 5%）。

    Returns:
        符合條件的交易日 DataFrame，依跌幅由大到小排序。
    """
    drops = df[df["change_pct"] <= -threshold].copy()
    drops = drops.sort_values("change_pct")  # 最慘在前
    return drops


def find_top_drops(
    df: pd.DataFrame,
    top_n: int = 10,
    years: int | None = None,
) -> pd.DataFrame:
    """找出前 N 大單日跌幅的交易日。

    Args:
        df: 含 change_pct 欄位的 DataFrame。
        top_n: 取前幾名，預設 10。
        years: 限制近幾年，None 表示全時段。

    Returns:
        前 N 大跌幅交易日，依跌幅由大到小排序。
    """
    d = df.dropna(subset=["change_pct"]).copy()
    if years is not None:
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        d = d[pd.to_datetime(d["Date"]) >= cutoff]
    return d.nsmallest(top_n, "change_pct")


def find_top_gains(
    df: pd.DataFrame,
    top_n: int = 10,
    years: int | None = None,
) -> pd.DataFrame:
    """找出前 N 大單日漲幅的交易日。

    Args:
        df: 含 change_pct 欄位的 DataFrame。
        top_n: 取前幾名，預設 10。
        years: 限制近幾年，None 表示全時段。

    Returns:
        前 N 大漲幅交易日，依漲幅由大到小排序。
    """
    d = df.dropna(subset=["change_pct"]).copy()
    if years is not None:
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        d = d[pd.to_datetime(d["Date"]) >= cutoff]
    return d.nlargest(top_n, "change_pct")


def find_top_point_drops(
    df: pd.DataFrame,
    top_n: int = 10,
    years: int | None = None,
) -> pd.DataFrame:
    """找出前 N 大單日跌點的交易日。"""
    d = df.dropna(subset=["change_pt"]).copy()
    if years is not None:
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        d = d[pd.to_datetime(d["Date"]) >= cutoff]
    return d.nsmallest(top_n, "change_pt")


def find_top_point_gains(
    df: pd.DataFrame,
    top_n: int = 10,
    years: int | None = None,
) -> pd.DataFrame:
    """找出前 N 大單日漲點的交易日。"""
    d = df.dropna(subset=["change_pt"]).copy()
    if years is not None:
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        d = d[pd.to_datetime(d["Date"]) >= cutoff]
    return d.nlargest(top_n, "change_pt")


# ── 輸出報表 ──────────────────────────────────────────────────────────────────


def format_report(drops: pd.DataFrame, threshold: float) -> str:
    """產生純文字報表。

    Args:
        drops: 篩選後的跌幅 DataFrame。
        threshold: 使用的門檻值。

    Returns:
        格式化後的報表字串。
    """
    lines = [
        "=" * 65,
        f"  台股加權指數 單日跌幅 ≥ {threshold:.1f}% 的交易日",
        f"  共 {len(drops)} 筆",
        "=" * 65,
        f"{'#':<4} {'日期':<12} {'收盤指數':>10} {'前日收盤':>10} {'跌幅':>8}  事件",
        "-" * 65,
    ]

    for rank, (_, row) in enumerate(drops.iterrows(), start=1):
        date_str = pd.Timestamp(row["Date"]).strftime("%Y-%m-%d")
        event = KNOWN_EVENTS.get(date_str, "")
        lines.append(
            f"{rank:<4} {date_str:<12} "
            f"{row['Close']:>10,.2f} "
            f"{row['prev_close']:>10,.2f} "
            f"{row['change_pct']:>7.2f}%  {event}"
        )

    lines += [
        "-" * 65,
        "",
        "依年份統計：",
    ]

    drops_copy = drops.copy()
    drops_copy["Year"] = pd.to_datetime(drops_copy["Date"]).dt.year
    yearly = drops_copy.groupby("Year").size().sort_index()
    for year, count in yearly.items():
        lines.append(f"  {year}：{count} 次")

    lines.append("=" * 65)
    return "\n".join(lines)


def save_csv(drops: pd.DataFrame, output_path: str) -> None:
    """將結果存成 CSV。

    Args:
        drops: 篩選後的 DataFrame。
        output_path: 輸出路徑。
    """
    out = drops[["Date", "Close", "prev_close", "change_pct"]].copy()
    out.columns = ["日期", "收盤指數", "前日收盤", "跌幅(%)"]
    out["日期"] = pd.to_datetime(out["日期"]).dt.strftime("%Y-%m-%d")
    out["跌幅(%)"] = out["跌幅(%)"].round(2)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"💾 結果已存至：{output_path}")


# ── 空頭市場偵測 ──────────────────────────────────────────────────────────────

# 主要空頭事件（鍵為高點的 YYYY-MM）
BEAR_MARKET_EVENTS: dict[str, str] = {
    "1990-02": "台灣股市泡沫崩潰（高點 12,682 點）",
    "1994-01": "升息週期引發修正",
    "1997-08": "亞洲金融風暴",
    "2000-02": "科技泡沫崩潰（dot-com bubble）",
    "2007-10": "全球金融海嘯（雷曼兄弟破產）",
    "2010-12": "歐洲主權債務危機",
    "2011-01": "歐洲主權債務危機",
    "2015-04": "中國股市崩盤，全球景氣疑慮",
    "2015-05": "中國股市崩盤，全球景氣疑慮",
    "2018-01": "美中貿易戰升溫",
    "2018-09": "美中貿易戰持續升溫",
    "2020-01": "COVID-19 疫情全球蔓延",
    "2022-01": "聯準會升息縮表打通膨",
    "2024-07": "AI 高估值修正＋日圓套利平倉",
    "2025-01": "川普對等關稅衝擊",
    "2025-02": "川普對等關稅衝擊",
}


def find_bear_markets(df: pd.DataFrame, threshold: float = 0.20) -> list[dict]:
    """找出所有高點到低點跌幅 >= threshold 的空頭市場。

    演算法：
      1. 從 search_from 掃描，更新高點直到出現 >= threshold 跌幅 → 確認空頭
      2. 繼續掃描找低點（直到恢復至高點水準或資料結束）
      3. 下一輪從低點之後繼續（確保中間的次級空頭也被捕捉）

    Returns:
        每個空頭的 dict：peak_date, peak_value, trough_date, trough_value,
        drop_pct, recovery_date, recovery_days, event
    """
    close = df["Close"].reset_index(drop=True).astype(float)
    dates = pd.to_datetime(df["Date"]).reset_index(drop=True)
    n = len(close)
    bears: list[dict] = []
    search_from = 0

    while search_from < n - 1:
        peak_i = search_from
        peak_p = float(close[search_from])
        found_bear = False

        for j in range(search_from + 1, n):
            pj = float(close[j])
            if pj > peak_p:
                peak_i = j
                peak_p = pj
            if (pj - peak_p) / peak_p <= -threshold:
                found_bear = True
                break

        if not found_bear:
            break

        # 找低點：從高點往後掃，直到回到高點水準或資料結束
        trough_i = peak_i
        trough_p = peak_p
        recovery_i: int | None = None

        for k in range(peak_i + 1, n):
            pk = float(close[k])
            if pk < trough_p:
                trough_p = pk
                trough_i = k
            if pk >= peak_p:
                recovery_i = k
                break

        drop_pct = (trough_p - peak_p) / peak_p * 100
        peak_date = dates[peak_i]
        trough_date = dates[trough_i]
        ym = peak_date.strftime("%Y-%m")

        bears.append(
            {
                "peak_date": peak_date.strftime("%Y-%m-%d"),
                "peak_value": round(peak_p, 2),
                "trough_date": trough_date.strftime("%Y-%m-%d"),
                "trough_value": round(trough_p, 2),
                "drop_pct": round(drop_pct, 2),
                "recovery_date": (
                    dates[recovery_i].strftime("%Y-%m-%d")
                    if recovery_i is not None
                    else None
                ),
                "recovery_days": (
                    int((dates[recovery_i] - peak_date).days)
                    if recovery_i is not None
                    else None
                ),
                "event": BEAR_MARKET_EVENTS.get(ym, ""),
            }
        )

        # 從低點之後繼續，確保中間的次級空頭也被捕捉
        search_from = trough_i + 1

    return bears


# ── 連續漲跌天數 ──────────────────────────────────────────────────────────────


def find_longest_streaks(df: pd.DataFrame, top_n: int = 10) -> dict[str, list[dict]]:
    """找出連續上漲／連續下跌天數最長的區間。

    連續的定義：change_pct 同號（正為上漲、負為下跌，0 視為中斷）。

    Args:
        df: 含 Date、Close、prev_close、change_pct 欄位的 DataFrame（需先呼叫
            calculate_daily_returns）。
        top_n: 各方向取前幾名。

    Returns:
        {"up": [...], "down": [...]}，每筆包含 start_date、end_date、days、
        cumulative_pct（區間累積漲跌幅%）。依天數由多到少排序，同天數時
        依累積漲跌幅排序（up 取最大漲幅在前，down 取最大跌幅在前）。
    """
    d = df.dropna(subset=["change_pct"]).reset_index(drop=True)
    n = len(d)

    streaks: list[dict] = []
    i = 0
    while i < n:
        change = float(d.loc[i, "change_pct"])
        sign = 1 if change > 0 else (-1 if change < 0 else 0)
        if sign == 0:
            i += 1
            continue

        j = i
        while j + 1 < n:
            next_change = float(d.loc[j + 1, "change_pct"])
            next_sign = 1 if next_change > 0 else (-1 if next_change < 0 else 0)
            if next_sign != sign:
                break
            j += 1

        start_close = float(d.loc[i, "prev_close"])
        end_close = float(d.loc[j, "Close"])
        streaks.append({
            "direction": "up" if sign > 0 else "down",
            "start_date": pd.Timestamp(d.loc[i, "Date"]).strftime("%Y-%m-%d"),
            "end_date": pd.Timestamp(d.loc[j, "Date"]).strftime("%Y-%m-%d"),
            "days": j - i + 1,
            "cumulative_pct": round((end_close - start_close) / start_close * 100, 2),
        })
        i = j + 1

    up = sorted(
        (s for s in streaks if s["direction"] == "up"),
        key=lambda s: (-s["days"], -s["cumulative_pct"]),
    )[:top_n]
    down = sorted(
        (s for s in streaks if s["direction"] == "down"),
        key=lambda s: (-s["days"], s["cumulative_pct"]),
    )[:top_n]
    return {"up": up, "down": down}


# ── 大跌後報酬統計 ────────────────────────────────────────────────────────────


def analyze_post_drop_returns(
    df: pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
    horizons: tuple[int, ...] = (1, 5, 20, 60),
) -> dict:
    """統計單日跌幅 >= threshold 之後 N 個交易日的報酬與勝率。

    以大跌當日收盤價為基準（模擬「當天收盤價接刀」），計算之後第 N 個
    交易日收盤價的報酬率；用於回答「大跌後該不該進場」。

    Args:
        df: 含 Date、Close、change_pct 欄位的 DataFrame（需先呼叫
            calculate_daily_returns）。
        threshold: 跌幅門檻（正數，如 5 代表 >= 5%）。
        horizons: 要統計的交易日數列表。

    Returns:
        {"threshold": float, "sample_size": int, "horizons": [
            {"days": int, "avg_return_pct": float, "median_return_pct": float,
             "win_rate_pct": float, "sample_size": int,
             "events": [{"date": str, "drop_pct": float, "return_pct": float}, ...]}
            | {"days": int, "sample_size": 0}
            ...
        ]}
    """
    d = df.dropna(subset=["change_pct"]).reset_index(drop=True)
    closes = d["Close"].to_numpy()
    dates = d["Date"].to_numpy()
    change_pcts = d["change_pct"].to_numpy()
    n = len(d)
    drop_indices = d.index[d["change_pct"] <= -threshold].tolist()

    horizon_stats = []
    for h in horizons:
        events = [
            {
                "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                "drop_pct": round(float(change_pcts[i]), 2),
                "return_pct": round(float((closes[i + h] - closes[i]) / closes[i] * 100), 2),
            }
            for i in drop_indices
            if i + h < n
        ]
        if events:
            s = pd.Series([e["return_pct"] for e in events])
            horizon_stats.append({
                "days": h,
                "avg_return_pct": round(float(s.mean()), 2),
                "median_return_pct": round(float(s.median()), 2),
                "win_rate_pct": round(float((s > 0).mean() * 100), 2),
                "sample_size": len(events),
                "events": events,
            })
        else:
            horizon_stats.append({"days": h, "sample_size": 0})

    return {
        "threshold": threshold,
        "sample_size": len(drop_indices),
        "horizons": horizon_stats,
    }


# ── 大漲後報酬統計 ────────────────────────────────────────────────────────────


def analyze_post_gain_returns(
    df: pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
    horizons: tuple[int, ...] = (1, 5, 20, 60),
) -> dict:
    """統計單日漲幅 >= threshold 之後 N 個交易日的報酬與勝率。

    以大漲當日收盤價為基準，計算之後第 N 個交易日收盤價的報酬率；
    用於回答「大漲後追高該不該進場」。

    Args:
        df: 含 Date、Close、change_pct 欄位的 DataFrame（需先呼叫
            calculate_daily_returns）。
        threshold: 漲幅門檻（正數，如 5 代表 >= 5%）。
        horizons: 要統計的交易日數列表。

    Returns:
        {"threshold": float, "sample_size": int, "horizons": [
            {"days": int, "avg_return_pct": float, "median_return_pct": float,
             "win_rate_pct": float, "sample_size": int,
             "events": [{"date": str, "gain_pct": float, "return_pct": float}, ...]}
            | {"days": int, "sample_size": 0}
            ...
        ]}
    """
    d = df.dropna(subset=["change_pct"]).reset_index(drop=True)
    closes = d["Close"].to_numpy()
    dates = d["Date"].to_numpy()
    change_pcts = d["change_pct"].to_numpy()
    n = len(d)
    gain_indices = d.index[d["change_pct"] >= threshold].tolist()

    horizon_stats = []
    for h in horizons:
        events = [
            {
                "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                "gain_pct": round(float(change_pcts[i]), 2),
                "return_pct": round(float((closes[i + h] - closes[i]) / closes[i] * 100), 2),
            }
            for i in gain_indices
            if i + h < n
        ]
        if events:
            s = pd.Series([e["return_pct"] for e in events])
            horizon_stats.append({
                "days": h,
                "avg_return_pct": round(float(s.mean()), 2),
                "median_return_pct": round(float(s.median()), 2),
                "win_rate_pct": round(float((s > 0).mean() * 100), 2),
                "sample_size": len(events),
                "events": events,
            })
        else:
            horizon_stats.append({"days": h, "sample_size": 0})

    return {
        "threshold": threshold,
        "sample_size": len(gain_indices),
        "horizons": horizon_stats,
    }


# ── 跌破均線後報酬統計 ────────────────────────────────────────────────────────


def analyze_ma_touch_returns(
    df: pd.DataFrame,
    ma_window: int,
    horizons: tuple[int, ...] = (1, 5, 20, 60),
) -> dict:
    """統計價格由上向下首次跌破 N 日均線之後 M 個交易日的報酬與勝率。

    「跌破」以當天最低價（盤中）判定：只要當天最低價跌破均線就算跌破，
    不論當天收盤是否還在均線之上。只在轉折當天算一次事件：前一天最低價
    高於均線、當天最低價小於等於均線；同一段下跌若連續多天最低價都在
    均線之下，只計入起跌的那天。

    Args:
        df: 含 Date、Close、Low 欄位的 DataFrame。
        ma_window: 均線天數（如 120 代表 120 日均線）。
        horizons: 要統計的交易日數列表。

    Returns:
        {"ma_window": int, "sample_size": int, "horizons": [
            {"days": int, "avg_return_pct": float, "median_return_pct": float,
             "win_rate_pct": float, "sample_size": int,
             "events": [{"date": str, "touch_pct": float, "return_pct": float}, ...]}
            | {"days": int, "sample_size": 0}
            ...
        ]}
    """
    d = df.sort_values("Date").reset_index(drop=True)
    closes = d["Close"].to_numpy()
    lows = d["Low"].to_numpy()
    dates = d["Date"].to_numpy()
    ma = d["Close"].rolling(ma_window).mean().to_numpy()
    n = len(d)

    touch_indices = [
        i
        for i in range(1, n)
        if not pd.isna(ma[i])
        and not pd.isna(ma[i - 1])
        and lows[i - 1] > ma[i - 1]
        and lows[i] <= ma[i]
    ]

    horizon_stats = []
    for h in horizons:
        events = [
            {
                "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                "touch_pct": round(float((lows[i] - ma[i]) / ma[i] * 100), 2),
                "return_pct": round(float((closes[i + h] - closes[i]) / closes[i] * 100), 2),
            }
            for i in touch_indices
            if i + h < n
        ]
        if events:
            s = pd.Series([e["return_pct"] for e in events])
            horizon_stats.append({
                "days": h,
                "avg_return_pct": round(float(s.mean()), 2),
                "median_return_pct": round(float(s.median()), 2),
                "win_rate_pct": round(float((s > 0).mean() * 100), 2),
                "sample_size": len(events),
                "events": events,
            })
        else:
            horizon_stats.append({"days": h, "sample_size": 0})

    return {
        "ma_window": ma_window,
        "sample_size": len(touch_indices),
        "horizons": horizon_stats,
    }


# ── 距離熊市 ──────────────────────────────────────────────────────────────────


def analyze_bear_market_distance(df: pd.DataFrame, threshold: float = 0.20) -> dict:
    """計算最新收盤價距離「自歷史高點下跌 threshold」熊市門檻還差多少點與百分比。

    以資料中最新一筆收盤價為基準，找出至今的歷史高點（以最高價 High 認定，含當天），
    門檻價 = 高點 * (1 - threshold)。若目前已跌破門檻，points_to_bear／
    pct_to_bear 會被限制在 0（不會是負值），改由 is_bear_market 標示已進入熊市。

    Args:
        df: 含 Date、Close、High 欄位的 DataFrame。
        threshold: 熊市跌幅門檻（正數，如 0.20 代表自高點下跌 20%）。

    Returns:
        {"as_of_date": str, "current_close": float, "peak_date": str,
         "peak_value": float, "current_drawdown_pct": float,
         "bear_threshold_pct": float, "bear_threshold_value": float,
         "points_to_bear": float, "pct_to_bear": float, "is_bear_market": bool}
    """
    d = df.sort_values("Date").reset_index(drop=True)
    close = d["Close"].astype(float)
    high = d["High"].astype(float)

    latest_date = pd.Timestamp(d["Date"].iloc[-1])
    latest_close = float(close.iloc[-1])

    peak_value = float(high.cummax().iloc[-1])
    peak_idx = int(high[high == peak_value].index[-1])
    peak_date = pd.Timestamp(d["Date"].iloc[peak_idx])

    threshold_value = peak_value * (1 - threshold)
    current_drawdown_pct = (latest_close - peak_value) / peak_value * 100
    is_bear_market = current_drawdown_pct <= -threshold * 100

    points_to_bear = max(0.0, latest_close - threshold_value)
    pct_to_bear = max(0.0, (latest_close - threshold_value) / latest_close * 100)

    return {
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "current_close": round(latest_close, 2),
        "peak_date": peak_date.strftime("%Y-%m-%d"),
        "peak_value": round(peak_value, 2),
        "current_drawdown_pct": round(current_drawdown_pct, 2),
        "bear_threshold_pct": round(-threshold * 100, 2),
        "bear_threshold_value": round(threshold_value, 2),
        "points_to_bear": round(points_to_bear, 2),
        "pct_to_bear": round(pct_to_bear, 2),
        "is_bear_market": bool(is_bear_market),
    }


# ── CLI 入口 ──────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """解析命令列參數。

    Returns:
        解析後的 Namespace 物件。
    """
    parser = argparse.ArgumentParser(
        description="篩選台股加權指數單日跌幅 >= N% 的交易日",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="CSV 檔案路徑（不指定則自動用 yfinance 下載）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        metavar="N",
        help=f"跌幅門檻（%%），預設 {DEFAULT_THRESHOLD}",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default="taiex_drops_result.csv",
        help="結果輸出 CSV 路徑，預設 taiex_drops_result.csv",
    )
    parser.add_argument(
        "--start",
        default=START_DATE,
        metavar="YYYY-MM-DD",
        help=f"起始日期（yfinance 模式），預設 {START_DATE}",
    )
    return parser.parse_args()


def main() -> None:
    """程式主流程。"""
    args = parse_args()

    # 1. 載入資料
    if args.csv:
        df = load_from_csv(args.csv)
    else:
        try:
            df = load_from_yfinance(start=args.start)
        except (ImportError, RuntimeError) as exc:
            print(f"❌ {exc}", file=sys.stderr)
            print(
                "\n💡 提示：請從證交所下載 CSV 後改用：\n"
                "   python taiex_big_drops.py --csv <你的檔案>.csv",
                file=sys.stderr,
            )
            sys.exit(1)

    # 2. 計算漲跌幅
    df = calculate_daily_returns(df)

    # 3. 篩選大跌日
    drops = find_big_drops(df, threshold=args.threshold)

    if drops.empty:
        print(f"ℹ️  資料期間內沒有單日跌幅 ≥ {args.threshold}% 的交易日。")
        return

    # 4. 輸出報表
    print()
    print(format_report(drops, threshold=args.threshold))

    # 5. 存 CSV
    save_csv(drops, args.output)


if __name__ == "__main__":
    main()
