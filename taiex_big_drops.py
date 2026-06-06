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
    "1990-08-23": "台灣泡沫崩潰 + 波灣戰爭",
    "2026-06-04": "美伊衝突升溫",
    # ── 漲幅事件 ──
    "2025-04-10": "川普宣布對等關稅暫緩 90 天",
    "2020-03-20": "COVID-19 恐慌後技術性反彈",
    "2008-10-30": "聯準會宣布降息救市",
    "2008-10-14": "G7 宣布協調救市行動",
    "2008-09-19": "美政府宣布 TARP 不良資產救助計畫",
    "2008-09-08": "美政府接管房利美、房地美",
    "2000-10-20": "科技泡沫後技術性反彈",
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
