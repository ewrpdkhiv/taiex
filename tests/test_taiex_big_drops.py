import pandas as pd
import pytest

from taiex_big_drops import (
    _parse_roc_or_ad_date,
    analyze_bear_market_distance,
    analyze_ma_touch_returns,
    analyze_post_drop_returns,
    calculate_daily_returns,
    find_bear_markets,
    find_longest_streaks,
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


# ── find_bear_markets ─────────────────────────────────────────────────────


def _make_df(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Date": dates, "Close": closes})


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


# ── analyze_bear_market_distance ──────────────────────────────────────────


class TestAnalyzeBearMarketDistance:
    def test_already_in_bear_market(self):
        df = _make_df([100, 120, 90])
        result = analyze_bear_market_distance(df, threshold=0.20)

        assert result["peak_value"] == 120
        assert result["current_close"] == 90
        assert result["current_drawdown_pct"] == pytest.approx(-25.0, abs=0.01)
        assert result["is_bear_market"] is True
        assert result["points_to_bear"] == 0
        assert result["pct_to_bear"] == 0

    def test_not_yet_bear_market(self):
        df = _make_df([100, 120, 110])
        result = analyze_bear_market_distance(df, threshold=0.20)

        assert result["is_bear_market"] is False
        assert result["current_drawdown_pct"] == pytest.approx(-8.33, abs=0.01)
        assert result["bear_threshold_value"] == 96
        assert result["points_to_bear"] == pytest.approx(14.0, abs=0.01)
        assert result["pct_to_bear"] == pytest.approx(14 / 110 * 100, abs=0.01)


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
