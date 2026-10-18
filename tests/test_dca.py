import pandas as pd
import pytest

from dca import _max_drawdown, _merge_extra_buys, _xirr, run_yearly


# ── _xirr ─────────────────────────────────────────────────────────────────


class TestXirr:
    def test_too_few_cashflows_returns_none(self):
        assert _xirr([(pd.Timestamp("2020-01-01"), -1000.0)]) is None
        assert _xirr([]) is None

    def test_single_period_ten_percent_return(self):
        # -1000 流出，一年後回收 1100 → IRR = 10%
        cashflows = [
            (pd.Timestamp("2020-01-01"), -1000.0),
            (pd.Timestamp("2021-01-01"), 1100.0),
        ]
        result = _xirr(cashflows)
        assert result == pytest.approx(10.0, abs=0.2)

    def test_zero_return(self):
        # 流入等於流出，IRR 應接近 0%
        cashflows = [
            (pd.Timestamp("2020-01-01"), -1000.0),
            (pd.Timestamp("2021-01-01"), 1000.0),
        ]
        result = _xirr(cashflows)
        assert result == pytest.approx(0.0, abs=0.2)

    def test_negative_return(self):
        # 虧損：投入 1000，一年後只剩 800 → IRR 為負
        cashflows = [
            (pd.Timestamp("2020-01-01"), -1000.0),
            (pd.Timestamp("2021-01-01"), 800.0),
        ]
        result = _xirr(cashflows)
        assert result is not None
        assert result < 0

    def test_multiple_cashflows(self):
        # 分批投入後最終回收，IRR 應介於合理區間內（正報酬）
        cashflows = [
            (pd.Timestamp("2020-01-01"), -1000.0),
            (pd.Timestamp("2020-07-01"), -1000.0),
            (pd.Timestamp("2021-01-01"), 2500.0),
        ]
        result = _xirr(cashflows)
        assert result is not None
        assert result > 0


# ── _max_drawdown ─────────────────────────────────────────────────────────


class TestMaxDrawdown:
    def test_no_share_events_returns_none(self):
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        close = pd.Series([100, 110, 90], index=dates)
        assert _max_drawdown([], close, dates) is None

    def test_known_drawdown_percentage(self):
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        close = pd.Series([100, 120, 80, 90, 110], index=dates)
        share_events = [(dates[0], 10.0)]  # 第一天買入 10 股

        # 市值序列：1000, 1200(peak), 800, 900, 1100
        # 最大回撤 = (800 - 1200) / 1200 = -33.33%
        result = _max_drawdown(share_events, close, dates)
        assert result == pytest.approx(-33.33, abs=0.01)

    def test_monotonically_rising_price_has_zero_drawdown(self):
        dates = pd.date_range("2020-01-01", periods=4, freq="D")
        close = pd.Series([100, 110, 120, 130], index=dates)
        share_events = [(dates[0], 5.0)]

        result = _max_drawdown(share_events, close, dates)
        assert result == 0.0


# ── _merge_extra_buys ────────────────────────────────────────────────────


class TestMergeExtraBuys:
    def _trading_dates(self):
        # 2020-01-01 起連續 10 個日曆天（未特意排除假日，測試不依賴此假設）
        return pd.date_range("2020-01-01", periods=10, freq="D")

    def test_no_extra_buys_returns_original(self):
        dates = self._trading_dates()
        buy_events = {dates[0]: 1000.0}
        result = _merge_extra_buys(buy_events, None, dates)
        assert result == buy_events

    def test_extra_buy_on_new_date_is_added(self):
        dates = self._trading_dates()
        buy_events = {dates[0]: 1000.0}
        extra = {dates[3]: 2000.0}
        result = _merge_extra_buys(buy_events, extra, dates)
        assert result[dates[0]] == 1000.0
        assert result[dates[3]] == 2000.0

    def test_extra_buy_colliding_with_existing_date_sums_amounts(self):
        dates = self._trading_dates()
        buy_events = {dates[2]: 1000.0}
        extra = {dates[2]: 2000.0}
        result = _merge_extra_buys(buy_events, extra, dates)
        assert result[dates[2]] == 3000.0

    def test_extra_buy_outside_range_is_ignored(self):
        dates = self._trading_dates()
        buy_events = {dates[0]: 1000.0}
        before_range = dates[0] - pd.Timedelta(days=5)
        after_range = dates[-1] + pd.Timedelta(days=5)
        extra = {before_range: 500.0, after_range: 500.0}
        result = _merge_extra_buys(buy_events, extra, dates)
        assert result == buy_events

    def test_original_buy_events_not_mutated(self):
        dates = self._trading_dates()
        buy_events = {dates[0]: 1000.0}
        _merge_extra_buys(buy_events, {dates[3]: 500.0}, dates)
        assert dates[3] not in buy_events


# ── run_yearly ───────────────────────────────────────────────────────────


class TestRunYearly:
    def _hist(self, start, end, price_fn):
        dates = pd.bdate_range(start, end)
        return pd.DataFrame({
            "Date": dates,
            "Close": [price_fn(d) for d in dates],
            "Dividends": 0.0,
        })

    def test_each_year_buys_twelve_times_and_flat_price_has_zero_irr(self):
        hist = self._hist("2020-01-01", "2023-06-30", lambda d: 100.0)
        out = run_yearly({"X": (hist, None)}, monthly_amount=1000, years=2,
                         today=pd.Timestamp("2023-06-30"))
        assert out["years"] == [2021, 2022, 2023]
        assert out["ytd_year"] == 2023
        by_year = out["results"][0]["by_year"]
        assert by_year["2021"]["months"] == 12
        assert by_year["2022"]["months"] == 12
        assert by_year["2023"]["months"] == 6  # YTD 只到 6 月
        assert by_year["2021"]["irr"] == pytest.approx(0.0, abs=0.01)

    def test_years_are_independent(self):
        # 2021 年價格上漲、2022 年價格下跌，各年 XIRR 應各自反映當年走勢
        def price(d):
            return 100.0 + d.dayofyear if d.year == 2021 else 400.0 - d.dayofyear
        hist = self._hist("2021-01-01", "2022-12-31", price)
        out = run_yearly({"X": (hist, None)}, monthly_amount=1000, years=1,
                         today=pd.Timestamp("2022-12-31"))
        by_year = out["results"][0]["by_year"]
        assert by_year["2021"]["irr"] > 0
        assert by_year["2022"]["irr"] < 0
