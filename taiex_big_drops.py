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


def load_from_yfinance(start: str = START_DATE) -> pd.DataFrame:
    """從 yfinance 下載台股加權指數歷史資料。

    Args:
        start: 起始日期字串，格式 YYYY-MM-DD。

    Returns:
        包含 Date、Close 欄位的 DataFrame。

    Raises:
        ImportError: yfinance 未安裝。
        RuntimeError: 下載失敗或資料為空。
    """
    try:
        import yfinance as yf  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError("請先安裝 yfinance：pip install yfinance") from exc

    print(f"⬇  從 Yahoo Finance 下載 {TAIEX_TICKER} 資料（{start} 至今）...")
    raw = yf.download(TAIEX_TICKER, start=start, progress=True, auto_adjust=True)

    if raw.empty:
        raise RuntimeError("下載失敗或資料為空。請確認網路連線，或改用 --csv 模式。")

    # yfinance 回傳 MultiIndex columns，拍平後只取 Close
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Close"]].copy()
    df.index.name = "Date"
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"])
    print(f"✅ 下載完成，共 {len(df):,} 筆交易日資料")
    return df


def load_ohlc_from_yfinance(start: str = START_DATE) -> pd.DataFrame:
    """從 yfinance 下載 TAIEX OHLC 資料（Date, Open, High, Low, Close）。"""
    try:
        import yfinance as yf  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError("請先安裝 yfinance：pip install yfinance") from exc

    raw = yf.download(TAIEX_TICKER, start=start, progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError("OHLC 資料下載失敗")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    cols = [c for c in ("Open", "High", "Low", "Close") if c in raw.columns]
    df = raw[cols].copy()
    df.index.name = "Date"
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def load_vix_from_yfinance(start: str = START_DATE) -> dict[str, float]:
    """下載 VIX 收盤價，回傳 {date_str: vix_close}。下載失敗回傳空 dict。"""
    try:
        import yfinance as yf  # pylint: disable=import-outside-toplevel
        raw = yf.download("^VIX", start=start, progress=False, auto_adjust=True)
        if raw.empty:
            return {}
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        result: dict[str, float] = {}
        for ts, row in raw.iterrows():
            try:
                result[pd.Timestamp(ts).strftime("%Y-%m-%d")] = round(float(row["Close"]), 2)
            except (KeyError, ValueError, TypeError):
                pass
        return result
    except Exception as e:
        print(f"⚠ VIX 下載失敗：{e}")
        return {}


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
    horizons: tuple[int, ...] = (5, 20, 60),
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
             "win_rate_pct": float, "sample_size": int} | {"days": int, "sample_size": 0}
            ...
        ]}
    """
    d = df.dropna(subset=["change_pct"]).reset_index(drop=True)
    closes = d["Close"].to_numpy()
    n = len(d)
    drop_indices = d.index[d["change_pct"] <= -threshold].tolist()

    horizon_stats = []
    for h in horizons:
        returns = [
            (closes[i + h] - closes[i]) / closes[i] * 100
            for i in drop_indices
            if i + h < n
        ]
        if returns:
            s = pd.Series(returns)
            horizon_stats.append({
                "days": h,
                "avg_return_pct": round(float(s.mean()), 2),
                "median_return_pct": round(float(s.median()), 2),
                "win_rate_pct": round(float((s > 0).mean() * 100), 2),
                "sample_size": len(returns),
            })
        else:
            horizon_stats.append({"days": h, "sample_size": 0})

    return {
        "threshold": threshold,
        "sample_size": len(drop_indices),
        "horizons": horizon_stats,
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
