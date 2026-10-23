from collections.abc import Sequence

import pandas as pd
import pytest

from taiex_big_drops import (
    EVENT_SHORT_NAMES,
    KNOWN_EVENTS,
    _parse_finmind_institutional,
    _parse_finmind_margin,
    _calc_margin_maintenance,
    _parse_roc_or_ad_date,
    _parse_twse_month_payload,
    analyze_bear_market_distance,
    analyze_holiday_returns,
    analyze_ma_touch_returns,
    analyze_post_drop_returns,
    analyze_post_gain_returns,
    calculate_daily_returns,
    find_bear_markets,
    find_longest_streaks,
    find_top_foreign_net_buys,
    find_top_foreign_net_sells,
    find_top_margin_changes,
    patch_missing_trading_days,
    rank_latest_day,
    rank_latest_foreign,
    rank_latest_margin,
    foreign_monthly_net,
    load_latest_margin,
    load_margin_maintenance,
)


# ── _parse_roc_or_ad_date ────────────────────────────────────────────────────


class TestParseRocOrAdDate:
    def test_roc_date(self):
        assert _parse_roc_or_ad_date("114/04/07") == pd.Timestamp("2025-04-07")

    def test_roc_date_single_digit(self):
        assert _parse_roc_or_ad_date("114/4/7") == pd.Timestamp("2025-04-07")

    def test_ad_date_with_slash(self):
        # 年份 >= 200 視為西元年，不加 1911
        assert _parse_roc_or_ad_date("2025/04/07") == pd.Timestamp("2025-04-07")

    def test_ad_date_with_dash(self):
        assert _parse_roc_or_ad_date("2025-04-07") == pd.Timestamp("2025-04-07")

    def test_invalid_string_returns_none(self):
        assert _parse_roc_or_ad_date("not-a-date") is None

    def test_invalid_month_returns_none(self):
        assert _parse_roc_or_ad_date("114/13/07") is None

    def test_non_numeric_slash_format_returns_none(self):
        assert _parse_roc_or_ad_date("abc/def/ghi") is None


# ── _parse_twse_month_payload ────────────────────────────────────────────


class TestParseTwseMonthPayload:
    def test_parses_real_api_shape(self):
        # 對應 TWSE MI_5MINS_HIST API 實際回傳格式（1999 年 2 月，含補行上班日
        # 星期六 88/02/20，這正是 yfinance 缺漏的那筆）
        payload = {
            "stat": "OK",
            "title": "88年02月 發行量加權股價指數歷史資料",
            "date": "19990201",
            "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
            "data": [
                [" 88/02/10", "5,669.23", "5,811.33", "5,669.23", "5,798.00"],
                [" 88/02/20", "6,040.57", "6,086.76", "5,977.01", "6,072.33"],
                [" 88/02/22", "6,216.01", "6,343.84", "6,168.94", "6,313.63"],
            ],
            "total": 3,
        }
        result = _parse_twse_month_payload(payload)

        assert list(result["Date"]) == [
            pd.Timestamp("1999-02-10"),
            pd.Timestamp("1999-02-20"),
            pd.Timestamp("1999-02-22"),
        ]
        row = result.iloc[1]
        assert row["Open"] == pytest.approx(6040.57)
        assert row["High"] == pytest.approx(6086.76)
        assert row["Low"] == pytest.approx(5977.01)
        assert row["Close"] == pytest.approx(6072.33)

    def test_non_ok_status_returns_empty(self):
        result = _parse_twse_month_payload({"stat": "查無資料", "data": []})
        assert result.empty
        assert list(result.columns) == ["Date", "Open", "High", "Low", "Close"]


# ── patch_missing_trading_days ────────────────────────────────────────────


class TestPatchMissingTradingDays:
    def test_inserts_dates_missing_from_source(self):
        # df 缺了 1999-02-20（補行上班日星期六），TWSE 官方資料裡有
        df = pd.DataFrame({
            "Date": [pd.Timestamp("1999-02-10"), pd.Timestamp("1999-02-22")],
            "Close": [5798.00, 6313.63],
        })

        def fake_fetch_month(year, month):
            if (year, month) != (1999, 2):
                return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close"])
            return pd.DataFrame([
                {"Date": pd.Timestamp("1999-02-10"), "Open": 5669.23, "High": 5811.33, "Low": 5669.23, "Close": 5798.00},
                {"Date": pd.Timestamp("1999-02-20"), "Open": 6040.57, "High": 6086.76, "Low": 5977.01, "Close": 6072.33},
                {"Date": pd.Timestamp("1999-02-22"), "Open": 6216.01, "High": 6343.84, "Low": 6168.94, "Close": 6313.63},
            ])

        result = patch_missing_trading_days(
            df,
            start="1999-01-01",
            end="1999-03-31",
            fetch_month=fake_fetch_month,
        )

        assert list(result["Date"]) == [
            pd.Timestamp("1999-02-10"),
            pd.Timestamp("1999-02-20"),
            pd.Timestamp("1999-02-22"),
        ]
        inserted = result[result["Date"] == pd.Timestamp("1999-02-20")].iloc[0]
        assert inserted["Close"] == pytest.approx(6072.33)

    def test_no_missing_dates_returns_original_df(self):
        df = pd.DataFrame({
            "Date": [pd.Timestamp("1999-02-10"), pd.Timestamp("1999-02-22")],
            "Close": [5798.00, 6313.63],
        })

        def fake_fetch_month(year, month):
            return pd.DataFrame([
                {"Date": pd.Timestamp("1999-02-10"), "Open": 0, "High": 0, "Low": 0, "Close": 5798.00},
                {"Date": pd.Timestamp("1999-02-22"), "Open": 0, "High": 0, "Low": 0, "Close": 6313.63},
            ])

        result = patch_missing_trading_days(
            df,
            start="1999-02-01",
            end="1999-02-28",
            fetch_month=fake_fetch_month,
        )

        assert result is df


# ── find_bear_markets ─────────────────────────────────────────────────────


def _make_df(closes: Sequence[float], lows: Sequence[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Date": dates, "Close": closes, "Low": lows or closes})


class TestFindBearMarkets:
    def test_no_bear_market_below_threshold(self):
        # 最大跌幅僅 10%，低於 20% 門檻
        df = _make_df([100, 105, 110, 99, 108])
        assert find_bear_markets(df, threshold=0.20) == []

    def test_single_bear_market_with_recovery(self):
        df = _make_df([100, 105, 110, 90, 95, 85, 111, 120])
        bears = find_bear_markets(df, threshold=0.20)

        assert len(bears) == 1
        bear = bears[0]
        assert bear["peak_date"] == "2020-01-03"
        assert bear["peak_value"] == 110
        assert bear["trough_date"] == "2020-01-06"
        assert bear["trough_value"] == 85
        assert bear["drop_pct"] == pytest.approx(-22.73, abs=0.01)
        assert bear["bear_days"] == 3
        assert bear["recovery_date"] == "2020-01-07"
        assert bear["recovery_days"] == 4

    def test_bear_market_without_recovery(self):
        # 資料結束前尚未回到高點，recovery 應為 None
        df = _make_df([100, 110, 80])
        bears = find_bear_markets(df, threshold=0.20)

        assert len(bears) == 1
        assert bears[0]["recovery_date"] is None
        assert bears[0]["recovery_days"] is None

    def test_two_consecutive_bear_markets(self):
        # 第一次空頭觸底恢復後，緊接著出現第二次空頭
        df = _make_df([100, 70, 100, 60, 100])
        bears = find_bear_markets(df, threshold=0.20)

        assert len(bears) == 2
        assert bears[0]["trough_value"] == 70
        assert bears[1]["trough_value"] == 60

    def test_uses_intraday_high_and_low(self):
        # 收盤最多只跌 ~18%（110→90），但盤中最高 120、最低 85 → 跌幅 29%
        df = pd.DataFrame({
            "Date": pd.date_range("2020-01-01", periods=5, freq="D"),
            "Close": [100, 110, 90, 95, 112],
            "High": [101, 120, 92, 96, 121],
            "Low": [99, 108, 85, 93, 110],
        })
        bears = find_bear_markets(df, threshold=0.20)

        assert len(bears) == 1
        bear = bears[0]
        assert bear["peak_date"] == "2020-01-02"
        assert bear["peak_value"] == 120
        assert bear["trough_date"] == "2020-01-03"
        assert bear["trough_value"] == 85
        assert bear["drop_pct"] == pytest.approx(-29.17, abs=0.01)
        # 收盤 112 未站回 120，但盤中最高 121 已觸及高點
        assert bear["recovery_date"] == "2020-01-05"

    def test_missing_high_low_falls_back_to_close(self):
        df = pd.DataFrame({
            "Date": pd.date_range("2020-01-01", periods=3, freq="D"),
            "Close": [100, 110, 80],
            "High": [100, float("nan"), 80],
            "Low": [100, 110, float("nan")],
        })
        bears = find_bear_markets(df, threshold=0.20)

        assert bears[0]["peak_value"] == 110
        assert bears[0]["trough_value"] == 80


# ── analyze_post_drop_returns ────────────────────────────────────────────


class TestAnalyzePostDropReturns:
    def _make_returns_df(self):
        # 索引 1（100→94，-6%）與索引 3（95→90，-5.26%）皆為 >=5% 大跌日
        closes = [100, 94, 95, 90, 92, 97, 99, 101, 103, 105]
        return calculate_daily_returns(_make_df(closes))

    def test_sample_size_counts_drop_days(self):
        df = self._make_returns_df()
        result = analyze_post_drop_returns(df, threshold=5.0, horizons=(2, 4))
        assert result["threshold"] == 5.0
        assert result["sample_size"] == 2

    def test_horizon_statistics(self):
        df = self._make_returns_df()
        result = analyze_post_drop_returns(df, threshold=5.0, horizons=(2, 4))
        by_days = {h["days"]: h for h in result["horizons"]}

        h2 = by_days[2]
        assert h2["sample_size"] == 2
        assert h2["avg_return_pct"] == pytest.approx(1.76, abs=0.01)
        assert h2["win_rate_pct"] == pytest.approx(50.0, abs=0.01)

        h4 = by_days[4]
        assert h4["sample_size"] == 2
        assert h4["avg_return_pct"] == pytest.approx(7.71, abs=0.01)
        assert h4["win_rate_pct"] == pytest.approx(100.0, abs=0.01)

    def test_horizon_includes_per_event_details(self):
        df = self._make_returns_df()
        result = analyze_post_drop_returns(df, threshold=5.0, horizons=(2,))
        events = result["horizons"][0]["events"]
        assert events == [
            {
                "date": "2020-01-02",
                "drop_pct": pytest.approx(-6.0, abs=0.01),
                "return_pct": pytest.approx(-4.26, abs=0.01),
            },
            {
                "date": "2020-01-04",
                "drop_pct": pytest.approx(-5.26, abs=0.01),
                "return_pct": pytest.approx(7.78, abs=0.01),
            },
        ]

    def test_horizon_beyond_available_data_has_zero_sample(self):
        df = self._make_returns_df()
        # 資料只有 10 筆，horizon=100 一定超出範圍
        result = analyze_post_drop_returns(df, threshold=5.0, horizons=(100,))
        assert result["horizons"][0] == {"days": 100, "sample_size": 0}

    def test_no_drops_above_threshold(self):
        df = calculate_daily_returns(_make_df([100, 101, 102, 103]))
        result = analyze_post_drop_returns(df, threshold=5.0, horizons=(1,))
        assert result["sample_size"] == 0
        assert result["horizons"][0] == {"days": 1, "sample_size": 0}


# ── analyze_post_gain_returns ────────────────────────────────────────────


class TestAnalyzePostGainReturns:
    def _make_returns_df(self):
        # 索引 1（100→106，+6%）與索引 3（100→105.26，+5.26%）皆為 >=5% 大漲日
        closes = [100, 106, 100, 105.26, 102, 97, 99, 101, 103, 105]
        return calculate_daily_returns(_make_df(closes))

    def test_sample_size_counts_gain_days(self):
        df = self._make_returns_df()
        result = analyze_post_gain_returns(df, threshold=5.0, horizons=(2, 4))
        assert result["threshold"] == 5.0
        assert result["sample_size"] == 2

    def test_horizon_includes_per_event_details(self):
        df = self._make_returns_df()
        result = analyze_post_gain_returns(df, threshold=5.0, horizons=(2,))
        events = result["horizons"][0]["events"]
        assert events == [
            {
                "date": "2020-01-02",
                "gain_pct": pytest.approx(6.0, abs=0.01),
                "return_pct": pytest.approx(-0.70, abs=0.01),
            },
            {
                "date": "2020-01-04",
                "gain_pct": pytest.approx(5.26, abs=0.01),
                "return_pct": pytest.approx(-7.85, abs=0.01),
            },
        ]

    def test_horizon_beyond_available_data_has_zero_sample(self):
        df = self._make_returns_df()
        # 資料只有 10 筆，horizon=100 一定超出範圍
        result = analyze_post_gain_returns(df, threshold=5.0, horizons=(100,))
        assert result["horizons"][0] == {"days": 100, "sample_size": 0}

    def test_no_gains_above_threshold(self):
        df = calculate_daily_returns(_make_df([100, 99, 98, 97]))
        result = analyze_post_gain_returns(df, threshold=5.0, horizons=(1,))
        assert result["sample_size"] == 0
        assert result["horizons"][0] == {"days": 1, "sample_size": 0}


# ── analyze_holiday_returns ─────────────────────────────────────────────


class TestAnalyzeHolidayReturns:
    def _make_df(self):
        # 2025 中秋為 10/6（週一），10/3（五）收盤後休市到 10/7（二）
        dates = pd.to_datetime([
            "2025-10-01", "2025-10-02", "2025-10-03",
            "2025-10-07", "2025-10-08", "2025-10-09",
        ])
        closes = [90, 95, 100, 102, 98, 110]
        return pd.DataFrame({"Date": dates, "Close": closes})

    def test_event_has_holiday_range_and_buy_sell_dates(self):
        result = analyze_holiday_returns(
            self._make_df(), ("2025-10-06",), horizons=(1,)
        )
        assert result["sample_size"] == 1
        assert result["horizons"][0]["events"] == [{
            "festival_date": "2025-10-06",
            "holiday_start": "2025-10-04",
            "holiday_end": "2025-10-06",
            "holiday_days": 3,
            "buy_date": "2025-10-03",
            "sell_date": "2025-10-07",
            "buy_close": 100.0,
            "sell_close": 102.0,
            "return_pct": pytest.approx(2.0, abs=0.01),
        }]

    def test_horizon_counts_from_first_day_after_holiday(self):
        result = analyze_holiday_returns(
            self._make_df(), ("2025-10-06",), horizons=(2, 3)
        )
        by_days = {h["days"]: h for h in result["horizons"]}
        assert by_days[2]["events"][0]["sell_date"] == "2025-10-08"
        assert by_days[2]["win_rate_pct"] == pytest.approx(0.0)
        assert by_days[3]["events"][0]["sell_date"] == "2025-10-09"
        assert by_days[3]["avg_return_pct"] == pytest.approx(10.0, abs=0.01)

    def test_horizon_beyond_available_data_has_zero_sample(self):
        result = analyze_holiday_returns(
            self._make_df(), ("2025-10-06",), horizons=(4,)
        )
        assert result["horizons"][0] == {"days": 4, "sample_size": 0}

    def test_lunar_new_year_uses_early_market_close(self):
        # 2024 過年：2/5（一）封關，初一 2/10，2/15（四）開紅盤
        df = pd.DataFrame({
            "Date": pd.to_datetime(["2024-02-02", "2024-02-05", "2024-02-15", "2024-02-16"]),
            "Close": [100, 100, 104, 106],
        })
        event = analyze_holiday_returns(df, ("2024-02-10",), horizons=(1,))["horizons"][0]["events"][0]
        assert event["buy_date"] == "2024-02-05"
        assert event["holiday_start"] == "2024-02-06"
        assert event["holiday_end"] == "2024-02-14"
        assert event["holiday_days"] == 9
        assert event["sell_date"] == "2024-02-15"
        assert event["return_pct"] == pytest.approx(4.0, abs=0.01)

    def test_skips_festival_outside_data_or_on_trading_day(self):
        result = analyze_holiday_returns(
            self._make_df(),
            # 2024 早於資料起點；10/2 在資料中有交易（非休市）
            ("2024-09-17", "2025-10-02"),
            horizons=(1,),
        )
        assert result["sample_size"] == 0
        assert result["horizons"][0] == {"days": 1, "sample_size": 0}


# ── analyze_ma_touch_returns ──────────────────────────────────────────────


class TestAnalyzeMaTouchReturns:
    def test_touch_event_and_returns(self):
        # MA3：索引 6 的異常高點推高均線，索引 7 收盤價回落至均線之下 → 觸及事件
        closes = [10, 10, 10, 10, 10, 10, 20, 10, 10, 10]
        df = _make_df(closes)
        result = analyze_ma_touch_returns(df, ma_window=3, horizons=(1, 2))

        assert result["ma_window"] == 3
        assert result["sample_size"] == 1

        by_days = {h["days"]: h for h in result["horizons"]}
        h1 = by_days[1]
        assert h1["sample_size"] == 1
        assert h1["events"] == [
            {
                "date": "2020-01-08",
                "touch_pct": pytest.approx(-25.0, abs=0.01),
                "return_pct": pytest.approx(0.0, abs=0.01),
            }
        ]

    def test_no_touch_when_always_above_ma(self):
        df = _make_df([100, 101, 102, 103, 104, 105])
        result = analyze_ma_touch_returns(df, ma_window=3, horizons=(1,))
        assert result["sample_size"] == 0
        assert result["horizons"][0] == {"days": 1, "sample_size": 0}

    def test_touch_detected_via_intraday_low_even_if_close_stays_above_ma(self):
        # 索引 6：收盤 12 仍高於 MA3(≈11.33)，但當天最低價 11 已跌破均線，
        # 前一天（索引 5）最低價 10.8 仍在均線之上 → 應算作一次跌破事件。
        closes = [10, 10, 10, 10, 10, 12, 12, 12, 10, 10]
        lows = [10, 10, 10, 10, 10, 10.8, 11, 10, 10, 10]
        df = _make_df(closes, lows)
        result = analyze_ma_touch_returns(df, ma_window=3, horizons=(1,))

        assert result["sample_size"] == 1
        h1 = result["horizons"][0]
        assert h1["events"] == [
            {
                "date": "2020-01-07",
                "touch_pct": pytest.approx(-2.94, abs=0.01),
                "return_pct": pytest.approx(0.0, abs=0.01),
            }
        ]


# ── analyze_bear_market_distance ──────────────────────────────────────────


class TestAnalyzeBearMarketDistance:
    def test_already_in_bear_market(self):
        df = _make_df([100, 120, 90])
        df["High"] = df["Close"]
        result = analyze_bear_market_distance(df, threshold=0.20)

        assert result["peak_value"] == 120
        assert result["current_close"] == 90
        assert result["current_drawdown_pct"] == pytest.approx(-25.0, abs=0.01)
        assert result["is_bear_market"] is True
        assert result["points_to_bear"] == 0
        assert result["pct_to_bear"] == 0

    def test_not_yet_bear_market(self):
        df = _make_df([100, 120, 110])
        df["High"] = df["Close"]
        result = analyze_bear_market_distance(df, threshold=0.20)

        assert result["is_bear_market"] is False
        assert result["current_drawdown_pct"] == pytest.approx(-8.33, abs=0.01)
        assert result["bear_threshold_value"] == 96
        assert result["points_to_bear"] == pytest.approx(14.0, abs=0.01)
        assert result["pct_to_bear"] == pytest.approx(14 / 110 * 100, abs=0.01)

    def test_peak_uses_intraday_high(self):
        # 盤中最高價創新高但收盤沒有 → 歷史高點以盤中最高價為準，與 find_bear_markets 一致
        df = _make_df([100, 95, 90])
        df["High"] = [100, 130, 90]
        result = analyze_bear_market_distance(df, threshold=0.20)

        assert result["peak_value"] == 130
        assert result["peak_date"] == "2020-01-02"
        assert result["bear_threshold_value"] == pytest.approx(104.0)
        assert result["is_bear_market"] is True

    def test_current_uses_intraday_low(self):
        # 收盤 100 只拉回 16.7%，但當天盤中最低 95 已跌破門檻 96 → 算進入熊市
        df = _make_df([100, 120, 100], lows=[100, 120, 95])
        df["High"] = df["Close"]
        result = analyze_bear_market_distance(df, threshold=0.20)

        assert result["current_close"] == 100
        assert result["current_low"] == 95
        assert result["current_drawdown_pct"] == pytest.approx(-20.83, abs=0.01)
        assert result["is_bear_market"] is True
        assert result["points_to_bear"] == 0


# ── find_longest_streaks ──────────────────────────────────────────────────


class TestFindLongestStreaks:
    def test_mixed_streaks_ranked_by_days(self):
        closes = [100, 105, 110, 108, 104, 100, 102, 106, 111, 117, 116]
        df = calculate_daily_returns(_make_df(closes))
        result = find_longest_streaks(df, top_n=10)

        assert len(result["up"]) == 2
        assert len(result["down"]) == 2

        assert result["up"][0]["days"] == 4
        assert result["up"][0]["start_date"] == "2020-01-07"
        assert result["up"][0]["end_date"] == "2020-01-10"
        assert result["up"][0]["cumulative_pct"] == pytest.approx(17.0, abs=0.01)
        assert result["up"][1]["days"] == 2

        assert result["down"][0]["days"] == 3
        assert result["down"][0]["cumulative_pct"] == pytest.approx(-9.09, abs=0.01)
        assert result["down"][1]["days"] == 1

    def test_all_up_has_no_down_streaks(self):
        df = calculate_daily_returns(_make_df([100, 101, 102, 103, 104]))
        result = find_longest_streaks(df, top_n=10)
        assert len(result["up"]) == 1
        assert result["up"][0]["days"] == 4
        assert result["down"] == []

    def test_zero_change_breaks_streak(self):
        df = calculate_daily_returns(_make_df([100, 101, 101, 102]))
        result = find_longest_streaks(df, top_n=10)
        # 101→101 漲跌幅為 0，中斷連續，拆成兩段各 1 天的上漲
        assert len(result["up"]) == 2
        assert all(s["days"] == 1 for s in result["up"])
        assert result["down"] == []

    def test_top_n_limits_results(self):
        closes = [100, 90, 100, 90, 100, 90, 100, 90]
        df = calculate_daily_returns(_make_df(closes))
        result = find_longest_streaks(df, top_n=1)
        assert len(result["down"]) == 1
        assert len(result["up"]) == 1


# ── 外資買賣超 ────────────────────────────────────────────────────────────────


class TestParseFinmindInstitutional:
    def test_sums_foreign_investor_and_foreign_dealer(self):
        payload = {"status": 200, "data": [
            {"date": "2025-04-07", "name": "Foreign_Investor", "buy": 100.0, "sell": 400.0},
            {"date": "2025-04-07", "name": "Foreign_Dealer_Self", "buy": 10.0, "sell": 30.0},
            {"date": "2025-04-07", "name": "Investment_Trust", "buy": 999.0, "sell": 0.0},
            {"date": "2025-04-08", "name": "Foreign_Investor", "buy": 50.0, "sell": 20.0},
        ]}
        df = _parse_finmind_institutional(payload)
        assert df["Date"].tolist() == [pd.Timestamp("2025-04-07"), pd.Timestamp("2025-04-08")]
        assert df["foreign_net"].tolist() == [-320.0, 30.0]

    def test_empty_payload(self):
        df = _parse_finmind_institutional({"status": 200, "data": []})
        assert df.empty
        assert list(df.columns) == ["Date", "foreign_net"]


class TestFindTopForeignNetSells:
    def test_ranks_by_net_sell_and_keeps_price_columns(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = calculate_daily_returns(pd.DataFrame({
            "Date": dates, "Close": [100.0, 98.0, 99.0, 95.0, 97.0],
        }))
        foreign = pd.DataFrame({
            "Date": dates, "foreign_net": [-999.0, -10.0, 5.0, -50.0, -30.0],
        })
        result = find_top_foreign_net_sells(df, foreign, top_n=2)
        # 首日沒有 change_pct 會被排除；買超日（正值）也不列入
        assert result["Date"].tolist() == [dates[3], dates[4]]
        assert result["foreign_net"].tolist() == [-50.0, -30.0]
        assert result["Close"].tolist() == [95.0, 97.0]


class TestFindTopForeignNetBuys:
    def test_ranks_by_net_buy_and_excludes_sells(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = calculate_daily_returns(pd.DataFrame({
            "Date": dates, "Close": [100.0, 98.0, 99.0, 95.0, 97.0],
        }))
        foreign = pd.DataFrame({
            "Date": dates, "foreign_net": [999.0, 10.0, -5.0, 50.0, 30.0],
        })
        result = find_top_foreign_net_buys(df, foreign, top_n=2)
        # 首日沒有 change_pct 會被排除；賣超日（負值）也不列入
        assert result["Date"].tolist() == [dates[3], dates[4]]
        assert result["foreign_net"].tolist() == [50.0, 30.0]



class TestRankLatestDay:
    def _df(self, closes):
        dates = pd.date_range("2025-01-01", periods=len(closes), freq="D")
        return calculate_daily_returns(pd.DataFrame({"Date": dates, "Close": closes}))

    def test_drop_day_ranked_among_drops(self):
        # -10%（-10 點）、+10%、-5%（-4.95 點）、-8%（-7.52 點，最新）→ 跌幅、跌點都第 2
        df = self._df([100.0, 90.0, 99.0, 94.05, 86.526])
        r = rank_latest_day(df, periods={"all": None})
        assert r is not None
        assert r["direction"] == "drop"
        assert r["date"] == "2025-01-05"
        assert r["change_pct"] == -8.0
        assert r["ranks"]["all"] == {"pct": 2, "pt": 2, "total": 3}

    def test_gain_day_ranked_among_gains(self):
        df = self._df([100.0, 110.0, 99.0, 102.0])
        r = rank_latest_day(df, periods={"all": None})
        assert r is not None
        assert r["direction"] == "gain"
        assert r["ranks"]["all"] == {"pct": 2, "pt": 2, "total": 2}

    def test_flat_day_has_no_ranks(self):
        r = rank_latest_day(self._df([100.0, 90.0, 90.0]), periods={"all": None})
        assert r is not None
        assert r["direction"] == "flat"
        assert r["ranks"] == {}


class TestRankLatestForeign:
    def test_latest_sell_ranked_among_sells(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = calculate_daily_returns(pd.DataFrame({
            "Date": dates, "Close": [100.0, 98.0, 99.0, 95.0, 97.0],
        }))
        foreign = pd.DataFrame({
            "Date": dates, "foreign_net": [-999e8, -10e8, 5e8, -50e8, -30e8],
        })
        r = rank_latest_foreign(df, foreign, periods={"all": None})
        # 首日無漲跌被排除（與排行表一致）→ 賣超日 -10、-50、-30，-30 排第 2
        assert r == {
            "date": "2025-01-05", "foreign_net": -30.0, "direction": "sell",
            "ranks": {"all": {"rank": 2, "total": 3}},
            "streak": 2,
            "streak_days": [
                {"date": "2025-01-04", "foreign_net": -50.0},
                {"date": "2025-01-05", "foreign_net": -30.0},
            ],
        }

    def test_latest_buy_uses_latest_foreign_date(self):
        dates = pd.date_range("2025-01-01", periods=4, freq="D")
        df = calculate_daily_returns(pd.DataFrame({
            "Date": dates, "Close": [100.0, 101.0, 102.0, 103.0],
        }))
        # 外資資料只到第 3 天（尚未公布最新一天）
        foreign = pd.DataFrame({"Date": dates[:3], "foreign_net": [1e8, 20e8, 30e8]})
        r = rank_latest_foreign(df, foreign, periods={"all": None})
        assert r is not None
        assert r["date"] == "2025-01-03"
        assert r["direction"] == "buy"
        assert r["ranks"]["all"] == {"rank": 1, "total": 2}
        assert r["streak"] == 2

    def test_streak_counts_back_until_direction_changes(self):
        dates = pd.date_range("2025-01-01", periods=6, freq="D")
        df = calculate_daily_returns(pd.DataFrame({
            "Date": dates, "Close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        }))
        foreign = pd.DataFrame({
            "Date": dates, "foreign_net": [-1e8, -2e8, 3e8, -4e8, -5e8, -6e8],
        })
        r = rank_latest_foreign(df, foreign, periods={"all": None})
        assert r is not None
        assert r["direction"] == "sell"
        assert r["streak"] == 3
        assert [x["date"] for x in r["streak_days"]] == ["2025-01-04", "2025-01-05", "2025-01-06"]
        assert [x["foreign_net"] for x in r["streak_days"]] == [-4.0, -5.0, -6.0]

    def test_flat_has_zero_streak(self):
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        df = calculate_daily_returns(pd.DataFrame({"Date": dates, "Close": [100.0, 101.0, 102.0]}))
        foreign = pd.DataFrame({"Date": dates, "foreign_net": [1e8, 2e8, 0.0]})
        r = rank_latest_foreign(df, foreign, periods={"all": None})
        assert r is not None
        assert r["direction"] == "flat"
        assert r["streak"] == 0
        assert r["streak_days"] == []


class TestForeignMonthlyNet:
    def test_sums_by_month(self):
        foreign = pd.DataFrame({
            "Date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-02-03"]),
            "foreign_net": [10e8, -30e8, 0.0, 5e8],
        })
        assert foreign_monthly_net(foreign) == [
            {"month": "2025-01", "foreign_net": -20.0, "buy_days": 1, "sell_days": 1},
            {"month": "2025-02", "foreign_net": 5.0, "buy_days": 1, "sell_days": 0},
        ]

    def test_empty(self):
        assert foreign_monthly_net(pd.DataFrame({"Date": [], "foreign_net": []})) == []


class TestEventShortNames:
    def test_every_event_has_short_name(self):
        assert set(EVENT_SHORT_NAMES) == set(KNOWN_EVENTS)

    def test_short_names_are_short(self):
        assert all(len(s) <= 10 for s in EVENT_SHORT_NAMES.values())


# ── 融資餘額／維持率 ──────────────────────────────────────────────────────────


class TestParseFinmindMargin:
    def test_keeps_margin_money_rows(self):
        payload = {"status": 200, "data": [
            {"date": "2025-04-08", "name": "MarginPurchaseMoney", "TodayBalance": 305.5e8, "YesBalance": 300e8},
            {"date": "2025-04-07", "name": "MarginPurchaseMoney", "TodayBalance": 300e8, "YesBalance": 320e8},
            {"date": "2025-04-08", "name": "MarginPurchase", "TodayBalance": 999, "YesBalance": 1},
        ]}
        df = _parse_finmind_margin(payload)
        assert df["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-04-07", "2025-04-08"]
        assert df["margin_balance"].tolist() == [300e8, 305.5e8]
        assert df["margin_change"].tolist() == [-20e8, 5.5e8]

    def test_no_margin_money_rows(self):
        df = _parse_finmind_margin({"status": 200, "data": []})
        assert df.empty
        assert list(df.columns) == ["Date", "margin_balance", "margin_change"]


def _margin_history(changes_yi: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """指數 df（第一天無漲跌）與同日期的融資 df（margin_change 單位：元）。"""
    dates = pd.date_range("2025-01-01", periods=len(changes_yi), freq="D")
    df = calculate_daily_returns(_make_df([100 + i for i in range(len(changes_yi))]))
    df["Date"] = dates
    margin = pd.DataFrame({
        "Date": dates,
        "margin_balance": [3000e8 + i * 1e8 for i in range(len(changes_yi))],
        "margin_change": [c * 1e8 for c in changes_yi],
    })
    return df, margin


class TestFindTopMarginChanges:
    def test_increases_skip_first_day_without_index_change(self):
        df, margin = _margin_history([999, 10, -5, 50, 30])
        result = find_top_margin_changes(df, margin, top_n=2, increase=True)
        assert result["margin_change"].tolist() == [50e8, 30e8]

    def test_decreases(self):
        df, margin = _margin_history([-999, -10, 5, -50, -30])
        result = find_top_margin_changes(df, margin, top_n=2, increase=False)
        assert result["margin_change"].tolist() == [-50e8, -30e8]


class TestRankLatestMargin:
    def test_rank_among_same_direction(self):
        df, margin = _margin_history([0, -10, 5, -50, -30])
        r = rank_latest_margin(df, margin)
        assert r == {"date": "2025-01-05", "balance": 3004.0, "change": -30.0, "rank": 2, "total": 3}

    def test_flat_has_no_rank(self):
        df, margin = _margin_history([0, 5, 0])
        r = rank_latest_margin(df, margin)
        assert r is not None
        assert (r["rank"], r["total"]) == (None, None)


def _margin_payload(amount_k: str, lots: dict[str, str]) -> dict:
    return {"stat": "OK", "tables": [
        {"fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"], "data": [
            ["融資(交易單位)", "1", "1", "1", "1", "1"],
            ["融資金額(仟元)", "0", "0", "0", "0", amount_k],
        ]},
        {"fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                    "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額"],
         "data": [[code, "x", "0", "0", "0", "0", v, "0", "0", "0", "0", "0", "99,999"]
                  for code, v in lots.items()]},
    ]}


def _quotes_payload(closes: dict[str, str]) -> dict:
    return {"stat": "OK", "tables": [
        {"fields": ["證券代號", "證券名稱", "收盤價"], "data": [[c, "x", v] for c, v in closes.items()]},
    ]}


class TestCalcMarginMaintenance:
    def test_market_value_over_margin_amount(self):
        # 2,000 張 × 100 元 + 1,000 張 × 50 元 = 250,000 仟元；融資金額 150,000 仟元
        margin = _margin_payload("150,000", {"1111": "2,000", "2222": "1,000", "3333": "500"})
        quotes = _quotes_payload({"1111": "100.00", "2222": "50.00", "3333": "--"})
        assert _calc_margin_maintenance(margin, quotes) == 166.67

    def test_missing_tables(self):
        assert _calc_margin_maintenance({"stat": "OK", "tables": []}, _quotes_payload({})) is None


class TestLoadMarginMaintenance:
    def test_skips_holidays_and_reports_change(self):
        ratios = {"20250408": "100.00", "20250407": "110.00"}  # 04-06 週日無資料

        def fetch(url, params):
            close = ratios.get(params["date"])
            if close is None:
                return {"stat": "很抱歉，沒有符合條件的資料!"}
            if "MI_MARGN" in url:
                return _margin_payload("1,000", {"1111": "15"})
            return _quotes_payload({"1111": close})

        result = load_margin_maintenance(fetch=fetch, today=pd.Timestamp("2025-04-08"), pause=0)
        assert result == {"date": "2025-04-08", "ratio": 150.0, "change": -15.0}

    def test_no_data(self):
        result = load_margin_maintenance(
            max_days=3, fetch=lambda url, params: {"stat": "no"}, today=pd.Timestamp("2025-04-08"), pause=0,
        )
        assert result is None


class TestLoadLatestMargin:
    def test_one_source_failing_keeps_the_other(self):
        def load_maintenance():
            raise RuntimeError("boom")
        result = load_latest_margin(lambda: {"change": 100.0}, load_maintenance=load_maintenance)
        assert result is not None
        assert result["margin"]["change"] == 100.0
        assert result["maintenance"] is None

    def test_both_failing_returns_none(self):
        def fail(*_):
            raise RuntimeError("boom")
        assert load_latest_margin(fail, load_maintenance=fail) is None
