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
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
FOREIGN_START_DATE = "2004-04-07"
FOREIGN_INVESTOR_NAMES = ("Foreign_Investor", "Foreign_Dealer_Self")

# 已知重大事件標籤（跌幅與漲幅共用）
KNOWN_EVENTS: dict[str, str] = {
    # ── 跌幅事件 ──
    "2026-10-15": "美國 CPI 高於預期、費半重挫，外資單日賣超 3,025 億創紀錄，股匯雙殺",
    "2026-10-13": "中東局勢升溫、油價重回 100 美元，外資賣超 1,653 億",
    "2026-07-29": "長鑫掛牌衝擊記憶體股，費半重挫、韓股熔斷",
    "2026-07-28": "中國半導體利空衝擊晶片股，亞股去槓桿殺盤",
    "2026-07-17": "台積電法說後外資提款，費半重挫、中東局勢惡化（史上最大跌點）",
    "2026-06-26": "蘋果漲價、AI 估值疑慮拖累科技股，外資賣超 1,431 億",
    "2026-06-24": "費半前夜重挫 7.8%，外資單日賣超 1,774 億",
    "2026-06-08": "費城半導體崩跌 10%，博通財報展望未上修引發科技股拋售潮",
    "2026-06-04": "中東局勢升溫，台積電股東會後高檔獲利了結",
    "2026-03-09": "中東戰火擴大、油價飆漲，外資單日賣超逾 1,200 億",
    "2026-03-04": "美以聯手攻擊伊朗，中東戰火升溫引發全球避險賣壓",
    "2026-03-03": "美伊戰火延燒，外資賣超 947 億",
    "2025-11-21": "輝達財報利多不續、降息時點不明，外資單日賣超逾 900 億",
    "2025-04-09": "對等關稅正式生效",
    "2025-04-07": "川普對等關稅（史上最大跌幅）",
    "2025-03-31": "川普「解放日」關稅前夕恐慌賣壓",
    "2025-02-03": "春節後開紅盤補跌（DeepSeek 衝擊、川普對中加墨加徵關稅）",
    "2024-09-04": "美股半導體暴跌引發台股科技股賣壓",
    "2024-08-05": "日本升息引發全球套利平倉",
    "2024-08-02": "日圓套利平倉恐慌擴散（日銀升息後）",
    "2022-10-11": "美國祭出晶片出口管制新規，國慶連假後補跌",
    "2021-05-12": "本土疫情爆發、通膨疑慮升溫，台股連日重挫",
    "2020-03-19": "COVID-19 疫情恐慌",
    "2020-03-12": "COVID-19 疫情恐慌（WHO 宣布全球大流行）",
    "2020-01-30": "春節後開紅盤，COVID-19 疫情初期擴散恐慌",
    "2018-10-11": "美債殖利率飆升、美中貿易戰擔憂引發全球股災",
    "2018-02-06": "美股崩跌（道瓊單日重挫 1,175 點，波動率商品爆倉）",
    "2011-08-08": "美國主權信評遭 S&P 調降至 AA+",
    "2011-08-05": "歐債危機、美國經濟衰退疑慮引發美股重挫",
    "2008-11-06": "金融海嘯持續蔓延",
    "2008-10-08": "金融海嘯持續蔓延",
    "2008-10-06": "金融海嘯（雷曼兄弟破產後）",
    "2008-01-22": "美國經濟衰退疑慮引發全球股災",
    "2004-03-22": "319 槍擊案、總統大選爭議後首個交易日",
    "2001-09-13": "911 恐怖攻擊後全球股災",
    "2000-11-20": "科技泡沫崩潰後期",
    "2000-10-19": "科技泡沫崩潰持續",
    "2000-10-02": "科技泡沫崩潰持續",
    "2000-03-13": "科技泡沫崩潰",
    "1999-07-16": "李登輝「兩國論」引發台海危機",
    "1997-10-20": "亞洲金融風暴高峰",
    "1990-08-23": "台灣泡沫崩潰 + 波灣戰爭",
    # ── 漲幅事件 ──
    "2026-07-31": "微軟財報激勵費半大漲逾 8%、韓國政府救市，台積電漲停（史上最大漲點）",
    "2026-09-18": "富時指數調整、美國升息利空出盡，外資買超 870 億",
    "2026-08-05": "美伊談判露曙光、油價回落、美股創高，外資買超 903 億",
    "2026-07-21": "跌深反彈，台積電、聯發科等電子權值股領軍",
    "2026-06-22": "美伊展開和談、費半創新高，台積電創新天價",
    "2026-05-29": "MSCI 季度調整尾盤爆量，台積電創新高",
    "2026-05-25": "美伊停火協議接近完成、黃仁勳來台，外資回補",
    "2026-05-21": "輝達財報優於預期，外資回補 603 億",
    "2026-05-06": "美股科技股走強，台股連 3 天創高，外資買超 751 億",
    "2026-05-04": "美股創新高帶動，台積電大漲，台股首度站上 4 萬點",
    "2026-04-24": "台積電大漲逾 5% 創新天價，法人回補",
    "2026-04-08": "美伊同意停火兩週，油價跌破 100 美元，外資買超逾 1,100 億",
    "2026-04-01": "美伊衝突出現緩和訊號，川普表態願結束軍事行動",
    "2026-03-11": "川普暗示對伊朗戰事將結束，油價回落，外資回補",
    "2026-02-24": "AI/CPO 題材發威，外資買超 627 億，台積電創新高",
    "2025-04-23": "川普稱無意撤換鮑爾、對中關稅可望大降",
    "2025-04-10": "川普宣布對等關稅暫緩 90 天",
    "2024-08-07": "全球股災後跌深反彈",
    "2024-01-19": "台積電法說釋出正面展望、ADR 大漲近 10%，外資狂買台積電",
    "2023-01-30": "春節後開紅盤，外資大舉回補",
    "2021-05-18": "外資回補、融資大減，美國疫苗可望來台",
    "2020-03-24": "聯準會宣布無限量 QE",
    "2020-03-20": "國安基金宣布進場護盤，疫情恐慌後反彈",
    "2009-05-04": "陸資來台投資台股開放首日",
    "2009-04-30": "中國移動宣布入股遠傳，陸資來台題材引爆漲勢",
    "2008-10-30": "聯準會宣布降息救市",
    "2008-10-14": "G7 宣布協調救市行動",
    "2008-09-19": "美政府宣布 TARP 不良資產救助計畫",
    "2008-09-08": "美政府接管房利美、房地美",
    "2007-08-20": "聯準會意外調降重貼現率，次貸恐慌緩解",
    "2005-12-28": "飛利浦盤後大宗出售台積電持股（扣除後外資僅買超約 50 億）",
    "2001-12-06": "911 後景氣回穩，外資回補",
    "2000-10-20": "科技泡沫後技術性反彈",
    "1999-02-22": "亞洲金融風暴後強勁反彈",
    "1999-02-08": "亞洲金融風暴後急速反彈",
    "1997-10-21": "亞洲金融風暴後短期反彈",
}

# K 線圖上橫排顯示用的短名稱（4～8 字），完整說明見 KNOWN_EVENTS；兩者的鍵必須一致
EVENT_SHORT_NAMES: dict[str, str] = {
    # ── 跌幅事件 ──
    "2026-10-15": "CPI 超預期",
    "2026-10-13": "油價破百",
    "2026-07-29": "長鑫掛牌",
    "2026-07-28": "陸晶片利空",
    "2026-07-17": "台積法說殺盤",
    "2026-06-26": "蘋果漲價",
    "2026-06-24": "費半重挫",
    "2026-06-08": "博通財報",
    "2026-06-04": "股東會後回檔",
    "2026-03-09": "中東戰火擴大",
    "2026-03-04": "美以攻伊朗",
    "2026-03-03": "美伊戰火",
    "2025-11-21": "輝達利多不續",
    "2025-04-09": "對等關稅生效",
    "2025-04-07": "對等關稅",
    "2025-03-31": "解放日前夕",
    "2025-02-03": "DeepSeek",
    "2024-09-04": "半導體暴跌",
    "2024-08-05": "日圓套利平倉",
    "2024-08-02": "日銀升息",
    "2022-10-11": "晶片管制",
    "2021-05-12": "本土疫情",
    "2020-03-19": "疫情恐慌",
    "2020-03-12": "WHO 大流行",
    "2020-01-30": "疫情爆發",
    "2018-10-11": "貿易戰股災",
    "2018-02-06": "波動率爆倉",
    "2011-08-08": "美債降評",
    "2011-08-05": "歐債危機",
    "2008-11-06": "金融海嘯",
    "2008-10-08": "金融海嘯",
    "2008-10-06": "雷曼後股災",
    "2008-01-22": "全球股災",
    "2004-03-22": "319 槍擊案",
    "2001-09-13": "911 恐攻",
    "2000-11-20": "科技泡沫",
    "2000-10-19": "科技泡沫",
    "2000-10-02": "科技泡沫",
    "2000-03-13": "科技泡沫",
    "1999-07-16": "兩國論",
    "1997-10-20": "亞洲金融風暴",
    "1990-08-23": "波灣戰爭",
    # ── 漲幅事件 ──
    "2026-07-31": "史上最大漲點",
    "2026-09-18": "富時指數調整",
    "2026-08-05": "美伊談判曙光",
    "2026-07-21": "跌深反彈",
    "2026-06-22": "美伊和談",
    "2026-05-29": "MSCI 調整",
    "2026-05-25": "停火在望",
    "2026-05-21": "輝達財報",
    "2026-05-06": "美科技股走強",
    "2026-05-04": "站上 4 萬",
    "2026-04-24": "台積新天價",
    "2026-04-08": "美伊停火",
    "2026-04-01": "美伊緩和",
    "2026-03-11": "戰事將結束",
    "2026-02-24": "AI／CPO",
    "2025-04-23": "關稅可望降",
    "2025-04-10": "關稅暫緩",
    "2024-08-07": "股災反彈",
    "2024-01-19": "台積電法說",
    "2023-01-30": "春節開紅盤",
    "2021-05-18": "疫苗來台",
    "2020-03-24": "無限 QE",
    "2020-03-20": "國安基金",
    "2009-05-04": "陸資來台",
    "2009-04-30": "中移入股遠傳",
    "2008-10-30": "Fed 降息",
    "2008-10-14": "G7 救市",
    "2008-09-19": "TARP",
    "2008-09-08": "接管二房",
    "2007-08-20": "Fed 降重貼現率",
    "2005-12-28": "飛利浦賣台積電",
    "2001-12-06": "外資回補",
    "2000-10-20": "技術反彈",
    "1999-02-22": "強勁反彈",
    "1999-02-08": "急速反彈",
    "1997-10-21": "短期反彈",
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


def _load_close_from_yfinance(cache_name: str, ticker: str, label: str, start: str) -> dict[str, float]:
    """取得 ticker 收盤價（快取 cache/<cache_name>.csv + 增量抓取），回傳 {date_str: close}。失敗回傳空 dict。"""
    try:
        from price_cache import CACHE_DIR

        df = _cached_yf_download(CACHE_DIR / f"{cache_name}.csv", ticker, start, ["Close"])
        result: dict[str, float] = {}
        for _, row in df.iterrows():
            try:
                result[pd.Timestamp(row["Date"]).strftime("%Y-%m-%d")] = round(float(row["Close"]), 3)
            except (KeyError, ValueError, TypeError):
                pass
        return result
    except Exception as e:
        print(f"⚠ {label} 下載失敗：{e}")
        return {}


def load_vix_from_yfinance(start: str = START_DATE) -> dict[str, float]:
    """取得 VIX 收盤價，回傳 {date_str: vix_close}。失敗回傳空 dict。"""
    return _load_close_from_yfinance("index/VIX", "^VIX", "VIX", start)


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


def _parse_finmind_institutional(payload: dict) -> pd.DataFrame:
    """解析 FinMind「TaiwanStockTotalInstitutionalInvestors」回傳的 JSON。

    外資買賣超 = 外資及陸資（Foreign_Investor）+ 外資自營商（Foreign_Dealer_Self，
    2018 年起才拆出）的買進金額 - 賣出金額，單位為新台幣元。

    Returns:
        含 Date、foreign_net 欄位的 DataFrame；查無資料回傳空表。
    """
    columns = ["Date", "foreign_net"]
    rows = [
        r for r in payload.get("data") or []
        if r.get("name") in FOREIGN_INVESTOR_NAMES
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    raw = pd.DataFrame(rows)
    raw["foreign_net"] = raw["buy"].astype(float) - raw["sell"].astype(float)
    raw["Date"] = pd.to_datetime(raw["date"])
    return (
        raw.groupby("Date", as_index=False)["foreign_net"].sum()
        .sort_values("Date")
        .reset_index(drop=True)[columns]
    )


def _fetch_finmind_institutional(start: str) -> pd.DataFrame:
    """向 FinMind 查詢 start 起的全市場三大法人買賣金額，回傳外資每日買賣超。"""
    import requests  # pylint: disable=import-outside-toplevel

    resp = requests.get(
        FINMIND_API_URL,
        params={"dataset": "TaiwanStockTotalInstitutionalInvestors", "start_date": start},
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind 回傳錯誤：{payload.get('msg')}")
    return _parse_finmind_institutional(payload)


def load_foreign_net(start: str = FOREIGN_START_DATE, fetch=_fetch_finmind_institutional) -> pd.DataFrame:
    """從快取 + FinMind 增量抓取外資每日買賣超（Date, foreign_net，單位：元）。

    Args:
        start: 起始日期；證交所三大法人統計自 2004-04-07 起才有資料。
        fetch: 抓取函式（接受起始日期字串），測試時可替換成假資料來源。
    """
    from price_cache import CACHE_DIR, OVERLAP_DAYS, _merge_frames, read_cache, write_cache

    cache_path = CACHE_DIR / "institutional" / "foreign_net.csv"
    cached = read_cache(cache_path)
    start_ts = pd.Timestamp(start)
    if cached is None or start_ts < cached["Date"].min():
        fetch_start = start
    else:
        fetch_start = max(
            start_ts, cached["Date"].max() - pd.Timedelta(days=OVERLAP_DAYS)
        ).strftime("%Y-%m-%d")

    combined = _merge_frames(cached, fetch(fetch_start))
    if combined.empty:
        raise RuntimeError("外資買賣超資料下載失敗")
    write_cache(cache_path, combined)
    return combined[combined["Date"] >= start_ts].reset_index(drop=True)


def find_top_foreign_net_sells(
    df: pd.DataFrame,
    foreign_df: pd.DataFrame,
    top_n: int = 10,
    years: int | None = None,
) -> pd.DataFrame:
    """找出外資單日賣超金額前 N 名的交易日，並附上當日指數漲跌。

    Args:
        df: 含 Date、Close、prev_close、change_pct、change_pt 欄位的 DataFrame。
        foreign_df: 含 Date、foreign_net 欄位的外資買賣超 DataFrame。
        top_n: 取前幾名，預設 10。
        years: 限制近幾年，None 表示全時段。

    Returns:
        依賣超金額由大到小排序的交易日（foreign_net 為負值）。
    """
    d = df.dropna(subset=["change_pct"]).merge(foreign_df, on="Date", how="inner")
    d = d[d["foreign_net"] < 0]
    if years is not None:
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        d = d[pd.to_datetime(d["Date"]) >= cutoff]
    return d.nsmallest(top_n, "foreign_net")


def find_top_foreign_net_buys(
    df: pd.DataFrame,
    foreign_df: pd.DataFrame,
    top_n: int = 10,
    years: int | None = None,
) -> pd.DataFrame:
    """找出外資單日買超金額前 N 名的交易日，並附上當日指數漲跌（參數同 find_top_foreign_net_sells）。

    Returns:
        依買超金額由大到小排序的交易日（foreign_net 為正值）。
    """
    d = df.dropna(subset=["change_pct"]).merge(foreign_df, on="Date", how="inner")
    d = d[d["foreign_net"] > 0]
    if years is not None:
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        d = d[pd.to_datetime(d["Date"]) >= cutoff]
    return d.nlargest(top_n, "foreign_net")


RANK_PERIODS: dict[str, int | None] = {"20y": 20, "10y": 10, "5y": 5, "all": None}


def _within_years(d: pd.DataFrame, years: int | None) -> pd.DataFrame:
    if years is None:
        return d
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
    return d[pd.to_datetime(d["Date"]) >= cutoff]


def _rank_of(values: pd.Series, value: float, *, smaller_first: bool) -> int:
    """value 在 values 中的名次（1 起算；同值並列取較前名次）。"""
    return int((values < value).sum() if smaller_first else (values > value).sum()) + 1


def rank_latest_day(
    df: pd.DataFrame, periods: dict[str, int | None] = RANK_PERIODS,
) -> dict | None:
    """最新交易日的漲跌在各期間的排名。

    下跌日排在「跌幅／跌點」排行、上漲日排在「漲幅／漲點」排行，
    total 為該期間同方向（下跌或上漲）的交易日數；平盤日 ranks 為空。
    """
    d = df.dropna(subset=["change_pct"])
    if d.empty:
        return None
    latest = d.iloc[-1]
    pct = float(latest["change_pct"])
    pt = float(latest["change_pt"])
    direction = "drop" if pct < 0 else "gain" if pct > 0 else "flat"
    ranks = {}
    if direction != "flat":
        is_drop = direction == "drop"
        for period, years in periods.items():
            w = _within_years(d, years)
            same = w[w["change_pct"] < 0] if is_drop else w[w["change_pct"] > 0]
            ranks[period] = {
                "pct": _rank_of(w["change_pct"], pct, smaller_first=is_drop),
                "pt": _rank_of(w["change_pt"], pt, smaller_first=is_drop),
                "total": len(same),
            }
    return {
        "date": pd.Timestamp(latest["Date"]).strftime("%Y-%m-%d"),
        "close": round(float(latest["Close"]), 2),
        "change_pct": round(pct, 2),
        "change_pt": round(pt, 2),
        "direction": direction,
        "ranks": ranks,
    }


def rank_latest_foreign(
    df: pd.DataFrame, foreign_df: pd.DataFrame, periods: dict[str, int | None] = RANK_PERIODS,
) -> dict | None:
    """最新一筆外資買賣超在各期間賣超（或買超）排行中的名次。

    與 find_top_foreign_net_sells/buys 用同一份資料範圍（需有指數漲跌的交易日），
    名次可直接對照排行表；foreign_net 單位：億元（負值為賣超）。
    streak 為截至最新一天連續同方向（賣超或買超）的交易日數，含最新一天；平盤為 0；
    streak_days 為這幾天的日期與金額（億元），依日期由舊到新。
    """
    d = df.dropna(subset=["change_pct"]).merge(foreign_df, on="Date", how="inner")
    if d.empty:
        return None
    latest = d.iloc[-1]
    net = float(latest["foreign_net"])
    direction = "sell" if net < 0 else "buy" if net > 0 else "flat"
    ranks = {}
    if direction != "flat":
        is_sell = direction == "sell"
        for period, years in periods.items():
            w = _within_years(d, years)
            same = w[w["foreign_net"] < 0] if is_sell else w[w["foreign_net"] > 0]
            ranks[period] = {
                "rank": _rank_of(same["foreign_net"], net, smaller_first=is_sell),
                "total": len(same),
            }
    streak = 0
    if direction != "flat":
        for v in reversed(d["foreign_net"].to_numpy()):
            if (v < 0) != is_sell or v == 0:
                break
            streak += 1
    tail = d.iloc[len(d) - streak:] if streak else d.iloc[0:0]
    streak_days = [
        {"date": pd.Timestamp(row.Date).strftime("%Y-%m-%d"), "foreign_net": round(float(row.foreign_net) / 1e8, 2)}
        for row in tail.itertuples()
    ]
    return {
        "date": pd.Timestamp(latest["Date"]).strftime("%Y-%m-%d"),
        "foreign_net": round(net / 1e8, 2),
        "direction": direction,
        "ranks": ranks,
        "streak": streak,
        "streak_days": streak_days,
    }


def foreign_monthly_net(foreign_df: pd.DataFrame) -> list[dict]:
    """外資每月買賣超合計（依月份由舊到新）。

    foreign_net 單位：億元（負值為賣超）；buy_days／sell_days 為當月買超／賣超的交易日數。
    """
    d = foreign_df.dropna(subset=["foreign_net"])
    if d.empty:
        return []
    month = pd.to_datetime(d["Date"]).dt.to_period("M")
    g = d.groupby(month)["foreign_net"]
    out = pd.DataFrame({
        "net": g.sum(),
        "buy_days": g.apply(lambda s: int((s > 0).sum())),
        "sell_days": g.apply(lambda s: int((s < 0).sum())),
    })
    return [
        {
            "month": str(m),
            "foreign_net": round(float(r.net) / 1e8, 2),
            "buy_days": int(r.buy_days),
            "sell_days": int(r.sell_days),
        }
        for m, r in out.iterrows()
    ]


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
    "1999-07": "李登輝「兩國論」引發台海緊張",
    "2000-02": "科技泡沫崩潰（dot-com bubble）",
    "2002-04": "全球科技股二次探底、美國企業會計醜聞",
    "2003-01": "美伊戰爭前夕、SARS 疫情",
    "2004-03": "319 槍擊案選舉爭議、中國宏觀調控",
    "2007-10": "全球金融海嘯（雷曼兄弟破產）",
    "2010-12": "歐洲主權債務危機",
    "2011-01": "歐洲主權債務危機",
    "2011-02": "歐洲主權債務危機、美國信評遭調降",
    "2015-04": "中國股市崩盤，全球景氣疑慮",
    "2015-05": "中國股市崩盤，全球景氣疑慮",
    "2018-01": "美中貿易戰升溫",
    "2018-09": "美中貿易戰持續升溫",
    "2020-01": "COVID-19 疫情全球蔓延",
    "2022-01": "聯準會升息縮表打通膨",
    "2024-07": "日圓套利平倉＋川普對等關稅衝擊",
    "2025-01": "川普對等關稅衝擊",
    "2025-02": "川普對等關稅衝擊",
}


def find_bear_markets(df: pd.DataFrame, threshold: float = 0.20) -> list[dict]:
    """找出所有高點到低點跌幅 >= threshold 的空頭市場。

    以盤中價格認定：高點取當日最高價（High）、低點取當日最低價（Low），
    回本以當日最高價重新觸及高點為準。df 若缺 High／Low 欄位（或該日為 NaN），
    改用收盤價代替。

    演算法：
      1. 從 search_from 掃描，更新高點直到出現 >= threshold 跌幅 → 確認空頭
      2. 繼續掃描找低點（直到恢復至高點水準或資料結束）
      3. 下一輪從低點之後繼續（確保中間的次級空頭也被捕捉）

    Returns:
        每個空頭的 dict：peak_date, peak_value, trough_date, trough_value,
        drop_pct, bear_days（空頭期間：高點→低點日曆天數）, recovery_date,
        recovery_days（回本天數：高點→重新站回高點的日曆天數）, event
    """
    close = df["Close"].reset_index(drop=True).astype(float)
    high = (
        df["High"].reset_index(drop=True).astype(float).fillna(close)
        if "High" in df else close
    )
    low = (
        df["Low"].reset_index(drop=True).astype(float).fillna(close)
        if "Low" in df else close
    )
    dates = pd.to_datetime(df["Date"]).reset_index(drop=True)
    n = len(close)
    bears: list[dict] = []
    search_from = 0

    while search_from < n - 1:
        peak_i = search_from
        peak_p = float(high[search_from])
        found_bear = False

        for j in range(search_from + 1, n):
            # 先以「之前的高點」檢查當日最低價，再用當日最高價更新高點
            if (float(low[j]) - peak_p) / peak_p <= -threshold:
                found_bear = True
                break
            if float(high[j]) > peak_p:
                peak_i = j
                peak_p = float(high[j])

        if not found_bear:
            break

        # 找低點：從高點往後掃，直到回到高點水準或資料結束
        trough_i = peak_i
        trough_p = peak_p
        recovery_i: int | None = None

        for k in range(peak_i + 1, n):
            if float(low[k]) < trough_p:
                trough_p = float(low[k])
                trough_i = k
            if float(high[k]) >= peak_p:
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
                "bear_days": int((trough_date - peak_date).days),
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


# ── 節日連假前買進後報酬統計（中秋、農曆新年、端午） ──────────────────────────

# 中秋節（農曆八月十五）、農曆新年（正月初一）與端午節（五月初五）的國曆日期，
# 以 lunardate 套件換算後寫死，避免為此新增依賴
MID_AUTUMN_DATES: tuple[str, ...] = (
    "1990-10-03", "1991-09-22", "1992-09-11", "1993-09-30", "1994-09-20",
    "1995-09-09", "1996-09-27", "1997-09-16", "1998-10-05", "1999-09-24",
    "2000-09-12", "2001-10-01", "2002-09-21", "2003-09-11", "2004-09-28",
    "2005-09-18", "2006-10-06", "2007-09-25", "2008-09-14", "2009-10-03",
    "2010-09-22", "2011-09-12", "2012-09-30", "2013-09-19", "2014-09-08",
    "2015-09-27", "2016-09-15", "2017-10-04", "2018-09-24", "2019-09-13",
    "2020-10-01", "2021-09-21", "2022-09-10", "2023-09-29", "2024-09-17",
    "2025-10-06", "2026-09-25", "2027-09-15", "2028-10-03", "2029-09-22",
    "2030-09-12", "2031-10-01", "2032-09-19", "2033-09-08", "2034-09-27",
    "2035-09-16",
)

LUNAR_NEW_YEAR_DATES: tuple[str, ...] = (
    "1990-01-27", "1991-02-15", "1992-02-04", "1993-01-23", "1994-02-10",
    "1995-01-31", "1996-02-19", "1997-02-07", "1998-01-28", "1999-02-16",
    "2000-02-05", "2001-01-24", "2002-02-12", "2003-02-01", "2004-01-22",
    "2005-02-09", "2006-01-29", "2007-02-18", "2008-02-07", "2009-01-26",
    "2010-02-14", "2011-02-03", "2012-01-23", "2013-02-10", "2014-01-31",
    "2015-02-19", "2016-02-08", "2017-01-28", "2018-02-16", "2019-02-05",
    "2020-01-25", "2021-02-12", "2022-02-01", "2023-01-22", "2024-02-10",
    "2025-01-29", "2026-02-17", "2027-02-06", "2028-01-26", "2029-02-13",
    "2030-02-03", "2031-01-23", "2032-02-11", "2033-01-31", "2034-02-19",
    "2035-02-08",
)


DRAGON_BOAT_DATES: tuple[str, ...] = (
    "1990-05-28", "1991-06-16", "1992-06-05", "1993-06-24", "1994-06-13",
    "1995-06-02", "1996-06-20", "1997-06-09", "1998-05-30", "1999-06-18",
    "2000-06-06", "2001-06-25", "2002-06-15", "2003-06-04", "2004-06-22",
    "2005-06-11", "2006-05-31", "2007-06-19", "2008-06-08", "2009-05-28",
    "2010-06-16", "2011-06-06", "2012-06-23", "2013-06-12", "2014-06-02",
    "2015-06-20", "2016-06-09", "2017-05-30", "2018-06-18", "2019-06-07",
    "2020-06-25", "2021-06-14", "2022-06-03", "2023-06-22", "2024-06-10",
    "2025-05-31", "2026-06-19", "2027-06-09", "2028-05-28", "2029-06-16",
    "2030-06-05", "2031-06-24", "2032-06-12", "2033-06-01", "2034-06-20",
    "2035-06-10",
)

def analyze_holiday_returns(
    df: pd.DataFrame,
    festival_dates: tuple[str, ...],
    horizons: tuple[int, ...] = (1, 5, 20, 60),
) -> dict:
    """統計「節日連假前最後一個交易日收盤買進、連假後第 N 個交易日收盤賣出」的報酬與勝率。

    連假範圍直接由交易資料推得：買進日 = 節日之前最後一個交易日（過年即封關日），
    連假結束後第 1 個交易日 = 節日之後第一個交易日（過年即開紅盤日），兩者之間
    沒有交易的日子即為連假（自動涵蓋週末、補假與過年提前封關）。賣出日為連假
    結束後第 N 個交易日（N=1 即連假後第一天）。若節日當天在資料中有交易紀錄
    （非休市），或資料未涵蓋該年節日前後，則略過該年。

    Args:
        df: 含 Date、Close 欄位的 DataFrame。
        festival_dates: 節日國曆日期（YYYY-MM-DD），如 MID_AUTUMN_DATES、
            LUNAR_NEW_YEAR_DATES、DRAGON_BOAT_DATES。
        horizons: 連假結束後第幾個交易日賣出。

    Returns:
        {"sample_size": int, "horizons": [
            {"days": int, "avg_return_pct": float, "median_return_pct": float,
             "win_rate_pct": float, "sample_size": int,
             "events": [{"festival_date": str, "holiday_start": str,
                         "holiday_end": str, "holiday_days": int,
                         "buy_date": str, "sell_date": str,
                         "buy_close": float, "sell_close": float,
                         "return_pct": float}, ...]}
            | {"days": int, "sample_size": 0}
            ...
        ]}
    """
    d = df.dropna(subset=["Close"]).sort_values("Date").reset_index(drop=True)
    dates = pd.to_datetime(d["Date"])
    closes = d["Close"].to_numpy()
    n = len(d)

    # 每年節日：(節日, 買進索引, 連假後第一個交易日索引)
    holidays: list[tuple[pd.Timestamp, int, int]] = []
    for s in festival_dates:
        festival = pd.Timestamp(s)
        if (dates == festival).any():
            continue
        before = dates.index[dates < festival]
        after = dates.index[dates > festival]
        if before.empty or after.empty:
            continue
        holidays.append((festival, int(before[-1]), int(after[0])))

    horizon_stats = []
    for h in horizons:
        events = []
        for festival, buy_i, resume_i in holidays:
            sell_i = resume_i + h - 1
            if sell_i >= n:
                continue
            holiday_start = dates[buy_i] + pd.Timedelta(days=1)
            holiday_end = dates[resume_i] - pd.Timedelta(days=1)
            events.append({
                "festival_date": festival.strftime("%Y-%m-%d"),
                "holiday_start": holiday_start.strftime("%Y-%m-%d"),
                "holiday_end": holiday_end.strftime("%Y-%m-%d"),
                "holiday_days": int((holiday_end - holiday_start).days) + 1,
                "buy_date": dates[buy_i].strftime("%Y-%m-%d"),
                "sell_date": dates[sell_i].strftime("%Y-%m-%d"),
                "buy_close": round(float(closes[buy_i]), 2),
                "sell_close": round(float(closes[sell_i]), 2),
                "return_pct": round(float((closes[sell_i] - closes[buy_i]) / closes[buy_i] * 100), 2),
            })
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
        "sample_size": len(holidays),
        "horizons": horizon_stats,
    }


# ── 距離熊市 ──────────────────────────────────────────────────────────────────


def analyze_bear_market_distance(df: pd.DataFrame, threshold: float = 0.20) -> dict:
    """計算最新盤中最低價距離「自歷史高點下跌 threshold」熊市門檻還差多少點與百分比。

    以資料中最新一筆的盤中最低價為基準，找出至今的歷史盤中最高價（含當天），
    門檻價 = 高點 * (1 - threshold)。與 find_bear_markets() 同樣以盤中最高／最低價
    認定；df 缺 High／Low 欄位（或該日為 NaN）時改用收盤價。若目前已跌破門檻，
    points_to_bear／pct_to_bear 會被限制在 0（不會是負值），改由 is_bear_market
    標示已進入熊市。

    Args:
        df: 含 Date、Close（可選 High、Low）欄位的 DataFrame。
        threshold: 熊市跌幅門檻（正數，如 0.20 代表自高點下跌 20%）。

    Returns:
        {"as_of_date": str, "current_close": float, "current_low": float,
         "peak_date": str, "peak_value": float, "current_drawdown_pct": float,
         "bear_threshold_pct": float, "bear_threshold_value": float,
         "points_to_bear": float, "pct_to_bear": float, "is_bear_market": bool}
    """
    d = df.sort_values("Date").reset_index(drop=True)
    close = d["Close"].astype(float)
    high = d["High"].astype(float).fillna(close) if "High" in d else close
    low = d["Low"].astype(float).fillna(close) if "Low" in d else close

    latest_date = pd.Timestamp(d["Date"].iloc[-1])
    latest_close = float(close.iloc[-1])
    latest_low = float(low.iloc[-1])

    peak_value = float(high.max())
    peak_idx = int(high[high == peak_value].index[-1])
    peak_date = pd.Timestamp(d["Date"].iloc[peak_idx])

    threshold_value = peak_value * (1 - threshold)
    current_drawdown_pct = (latest_low - peak_value) / peak_value * 100
    is_bear_market = current_drawdown_pct <= -threshold * 100

    points_to_bear = max(0.0, latest_low - threshold_value)
    pct_to_bear = max(0.0, (latest_low - threshold_value) / latest_low * 100)

    return {
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "current_close": round(latest_close, 2),
        "current_low": round(latest_low, 2),
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
