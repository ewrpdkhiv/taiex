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
    "00631L.TW": "元大台灣50正2",
    "SPY":  "SPDR S&P 500",
    "QQQ":  "Invesco Nasdaq-100",
    "SSO":  "ProShares S&P500 2x",
    "UPRO": "ProShares S&P500 3x",
    "QLD":  "ProShares Nasdaq-100 2x",
    "TQQQ": "ProShares Nasdaq-100 3x",
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
    share_events: list[tuple[pd.Timestamp, int]],
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
) -> dict | None:
    end_date = pd.Timestamp.now().normalize()
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
    month = pd.Timestamp(trading_dates[0].year, trading_dates[0].month, 1)
    last_date = trading_dates[-1]

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
    share_events: list[tuple[pd.Timestamp, int]] = []  # 最大回撤用

    invested = 0.0
    buy_count = 0
    actual_start: pd.Timestamp | None = None
    buy_history: list[tuple[pd.Timestamp, float]] = []

    for date in all_dates:
        if date > last_date:
            break

        # ① 股息次日：整股買入，零頭捨去
        if date in pending_re:
            if date in close.index:
                price = float(close[date])
                if not pd.isna(price) and price > 0:
                    qty = int(pending_re[date] / price)
                    if qty > 0:
                        shares += qty
                        share_events.append((date, qty))
            pending_re.pop(date)

        # ② 定期定額買入（整股，零頭捨去）
        if date in buy_events:
            if date in close.index:
                price = float(close[date])
                if not (pd.isna(price) or price <= 0):
                    qty = int(buy_events[date] / price)
                    if qty > 0:
                        actual_cost = qty * price
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

    last_price = float(close.iloc[-1])
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
        "reinvest": {
            "shares": shares,
            "market_value": round(market_value),
            "return_rate": round(return_rate, 2),
            "irr": irr,
            "max_drawdown": max_dd,
            "calmar": calmar,
        },
    }


def run_all(monthly_amount: int = 1_000_000, invest_day: int = 5, years: int = 10) -> list[dict]:
    common_start = (pd.Timestamp.now().normalize() - pd.DateOffset(years=years))
    print(f"📅 共同起始日（近 {years} 年）：{common_start.date()}")

    results = []
    for ticker in TICKERS:
        print(f"⬇  計算 {ticker}...")
        r = run_dca(ticker, monthly_amount, invest_day, years, force_start=common_start)
        if r:
            results.append(r)
    return results
