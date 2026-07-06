"""
定期定額模擬器：每月固定金額買入台灣 ETF，含股息處理。
"""

import pandas as pd
import yfinance as yf

TICKERS: dict[str, str] = {
    "0050.TW":   "元大台灣50",
    "0056.TW":   "元大高股息",
    "2317.TW":   "鴻海",
    "2330.TW":   "台積電",
    "2412.TW":   "中華電信",
    "2454.TW":   "聯發科",
    "2881.TW":   "富邦金控",
    "2884.TW":   "玉山金控",
    "2886.TW":   "兆豐金控",
    "2891.TW":   "中信金控",
    "2498.TW":   "宏達電",
    "00631L.TW": "元大台灣50正2",
    "00675L.TW": "富邦臺灣加權正2",
    "SPY":  "SPDR S&P 500",
    "QQQ":  "Invesco Nasdaq-100",
    "SSO":  "ProShares S&P500 2x",
    "UPRO": "ProShares S&P500 3x",
    "QLD":  "ProShares Nasdaq-100 2x",
    "TQQQ": "ProShares Nasdaq-100 3x",
    "VT":   "Vanguard 全球股票",
    "VTI":  "Vanguard 全美股票",
    "SOXX": "iShares 費城半導體",
    "SOXL": "Direxion 半導體 3x",
    "2603.TW": "長榮",
    "2609.TW": "陽明",
    "2615.TW": "萬海",
    "3231.TW": "緯創",
    "4128.TWO": "中天",
    "4192.TWO": "杏國",
    "4743.TWO": "合一",
    "1734.TW":  "杏輝",
    "3176.TWO": "基亞",
    "MU":    "Micron Technology",
    "GOOGL": "Alphabet (Google)",
}

TICKER_TAGS: dict[str, list[str]] = {
    "0050.TW":   ["tw", "etf"],
    "0056.TW":   ["tw", "etf"],
    "2317.TW":   ["tw", "stock"],
    "2330.TW":   ["tw", "stock"],
    "2412.TW":   ["tw", "stock"],
    "2454.TW":   ["tw", "stock"],
    "2881.TW":   ["tw", "stock", "finance"],
    "2884.TW":   ["tw", "stock", "finance"],
    "2886.TW":   ["tw", "stock", "finance"],
    "2891.TW":   ["tw", "stock", "finance"],
    "2498.TW":   ["tw", "stock"],
    "00631L.TW": ["tw", "etf", "leveraged"],
    "00675L.TW": ["tw", "etf", "leveraged"],
    "SPY":       ["us", "etf"],
    "QQQ":       ["us", "etf"],
    "SSO":       ["us", "etf", "leveraged"],
    "UPRO":      ["us", "etf", "leveraged"],
    "QLD":       ["us", "etf", "leveraged"],
    "TQQQ":      ["us", "etf", "leveraged"],
    "VT":        ["us", "etf"],
    "VTI":       ["us", "etf"],
    "SOXX":      ["us", "etf"],
    "SOXL":      ["us", "etf", "leveraged"],
    "2603.TW":   ["tw", "stock", "shipping"],
    "2609.TW":   ["tw", "stock", "shipping"],
    "2615.TW":   ["tw", "stock", "shipping"],
    "3231.TW":   ["tw", "stock"],
    "4128.TWO":  ["tw", "stock", "biotech"],
    "4192.TWO":  ["tw", "stock", "biotech"],
    "4743.TWO":  ["tw", "stock", "biotech"],
    "1734.TW":   ["tw", "stock", "biotech"],
    "3176.TWO":  ["tw", "stock", "biotech"],
    "MU":        ["us", "stock"],
    "GOOGL":     ["us", "stock"],
}


def _xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """年化 IRR（XIRR）。cashflows 為 (date, amount) 列表，流出為負值。"""
    if len(cashflows) < 2:
        return None
    t0 = cashflows[0][0]
    years = [(d - t0).days / 365.0 for d, _ in cashflows]
    amounts = [a for _, a in cashflows]

    def npv(r: float) -> float:
        try:
            return sum(a / (1.0 + r) ** t for a, t in zip(amounts, years))
        except (OverflowError, ZeroDivisionError):
            return float("nan")

    def dnpv(r: float) -> float:
        try:
            return sum(-t * a / (1.0 + r) ** (t + 1) for a, t in zip(amounts, years))
        except (OverflowError, ZeroDivisionError):
            return float("nan")

    r = 0.1
    for _ in range(300):
        f = npv(r)
        df = dnpv(r)
        if f != f or df != df or abs(df) < 1e-14:
            break
        step = f / df
        r -= step
        if r <= -1.0:
            r = -0.9999
        if abs(step) < 1e-9:
            return round(r * 100, 2)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo != f_lo or f_hi != f_hi or f_lo * f_hi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if f_mid != f_mid:
            return None
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return round((lo + hi) / 2.0 * 100, 2)


def _max_drawdown(
    share_events: list[tuple[pd.Timestamp, float]],
    close: pd.Series,
    trading_dates: pd.DatetimeIndex,
) -> float | None:
    """計算投資組合市值的最大回撤（%，負值）。"""
    if not share_events:
        return None
    events = sorted(share_events)
    first_date = events[0][0]
    event_idx = 0
    running_shares = 0
    peak = 0.0
    max_dd = 0.0

    for date in trading_dates:
        if date < first_date:
            continue
        while event_idx < len(events) and events[event_idx][0] <= date:
            running_shares += events[event_idx][1]
            event_idx += 1
        if running_shares <= 0 or date not in close.index:
            continue
        value = running_shares * float(close[date])
        if value > peak:
            peak = value
        if peak > 0:
            dd = (value - peak) / peak
            if dd < max_dd:
                max_dd = dd

    return round(max_dd * 100, 2) if max_dd < 0 else 0.0


def _next_trading_day(
    target: pd.Timestamp, trading_dates: pd.DatetimeIndex
) -> pd.Timestamp | None:
    future = trading_dates[trading_dates >= target]
    return future[0] if len(future) > 0 else None


def run_dca(
    ticker: str,
    monthly_amount: int = 1_000_000,
    invest_day: int = 5,
    years: int = 10,
    force_start: pd.Timestamp | None = None,
    force_end: pd.Timestamp | None = None,
) -> dict | None:
    end_date = force_end if force_end is not None else pd.Timestamp.now().normalize()
    start_date = force_start if force_start is not None else end_date - pd.DateOffset(years=years)

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=False,
        )
    except Exception as exc:
        print(f"❌ 下載 {ticker} 失敗：{exc}")
        return None

    if hist.empty or len(hist) < 12:
        return None

    hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
    trading_dates = hist.index
    close = hist["Close"]

    try:
        market_cap = stock.fast_info.market_cap
        if not market_cap:
            market_cap = stock.info.get("totalAssets")
    except Exception:
        try:
            market_cap = stock.info.get("totalAssets")
        except Exception:
            market_cap = None

    try:
        divs = stock.dividends
        if len(divs) > 0:
            divs.index = (
                divs.index.tz_localize(None) if divs.index.tz else divs.index
            )
            divs = divs[
                (divs.index >= trading_dates[0]) & (divs.index <= trading_dates[-1])
            ]
    except Exception:
        divs = pd.Series(dtype=float)

    buy_events: dict[pd.Timestamp, int] = {}
    last_date = trading_dates[-1]
    # 若 invest_day 已早於 start_date 當月的日，從下個月起算，確保整 10 年 = 120 次
    _first = trading_dates[0]
    if pd.Timestamp(_first.year, _first.month, invest_day) >= start_date:
        month = pd.Timestamp(_first.year, _first.month, 1)
    else:
        _m = _first + pd.DateOffset(months=1)
        month = pd.Timestamp(_m.year, _m.month, 1)

    while month <= last_date:
        target = pd.Timestamp(month.year, month.month, invest_day)
        actual = _next_trading_day(target, trading_dates)
        if actual is not None and actual <= last_date:
            buy_events[actual] = monthly_amount
        month += pd.DateOffset(months=1)

    if not buy_events:
        return None

    div_next_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for div_date in divs.index:
        nxt = trading_dates[trading_dates > div_date]
        if len(nxt) > 0:
            div_next_map[div_date] = nxt[0]

    all_dates = sorted(set(
        list(buy_events.keys()) +
        list(divs.index) +
        list(div_next_map.values())
    ))

    shares = 0
    pending_re: dict[pd.Timestamp, float] = {}
    share_events: list[tuple[pd.Timestamp, float]] = []  # 最大回撤用

    invested = 0.0
    buy_count = 0
    actual_start: pd.Timestamp | None = None
    buy_history: list[tuple[pd.Timestamp, float]] = []

    for date in all_dates:
        if date > last_date:
            break

        # ① 股息次日：小數股買入，全額投入
        if date in pending_re:
            if date in close.index:
                price = float(close[date])
                if not pd.isna(price) and price > 0:
                    qty = pending_re[date] / price
                    if qty > 0:
                        shares += qty
                        share_events.append((date, qty))
            pending_re.pop(date)

        # ② 定期定額買入（小數股，全額投入）
        if date in buy_events:
            if date in close.index:
                price = float(close[date])
                if not (pd.isna(price) or price <= 0):
                    qty = buy_events[date] / price
                    if qty > 0:
                        actual_cost = buy_events[date]
                        shares += qty
                        share_events.append((date, qty))
                        invested += actual_cost
                        buy_count += 1
                        buy_history.append((date, -actual_cost))
                        if actual_start is None:
                            actual_start = date

        # ③ 除息：次交易日整股買入
        if date in divs.index:
            div_per_share = float(divs[date])
            if pd.isna(div_per_share) or div_per_share <= 0:
                continue
            if date in div_next_map:
                nxt = div_next_map[date]
                pending_re[nxt] = pending_re.get(nxt, 0.0) + shares * div_per_share

    if invested <= 0 or actual_start is None:
        return None

    close_valid = close.dropna()
    if close_valid.empty:
        return None
    last_price = float(close_valid.iloc[-1])
    market_value = shares * last_price
    return_rate = (market_value - invested) / invested * 100
    irr = _xirr(buy_history + [(last_date, market_value)])
    max_dd = _max_drawdown(share_events, close, trading_dates)
    calmar = round(irr / abs(max_dd), 2) if (irr is not None and max_dd and max_dd != 0) else None

    return {
        "ticker": ticker,
        "name": TICKERS.get(ticker, ticker),
        "monthly_amount": monthly_amount,
        "invested": round(invested),
        "months": buy_count,
        "start_date": actual_start.strftime("%Y-%m-%d"),
        "end_date": last_date.strftime("%Y-%m-%d"),
        "last_price": round(last_price, 2),
        "market_cap": round(market_cap) if (market_cap and pd.notna(market_cap)) else None,
        "tags": TICKER_TAGS.get(ticker, []),
        "reinvest": {
            "shares": round(shares, 4),
            "market_value": round(market_value),
            "return_rate": round(return_rate, 2),
            "irr": irr,
            "max_drawdown": max_dd,
            "calmar": calmar,
        },
    }


def run_all(
    monthly_amount: int = 1_000_000,
    invest_day: int = 5,
    years: int = 10,
    force_end: pd.Timestamp | None = None,
    force_start: pd.Timestamp | None = None,
) -> list[dict]:
    end = force_end if force_end is not None else pd.Timestamp.now().normalize()
    common_start = force_start if force_start is not None else end - pd.DateOffset(years=years)
    print(f"📅 起始日：{common_start.date()}  結束日：{end.date()}")

    results = []
    for ticker in TICKERS:
        print(f"⬇  計算 {ticker}...")
        r = run_dca(ticker, monthly_amount, invest_day, years,
                    force_start=common_start, force_end=force_end)
        if r:
            results.append(r)
    return results
