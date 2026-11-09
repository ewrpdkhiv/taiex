import pandas as pd

from price_cache import _merge_frames


class TestMergeFrames:
    def test_empty_cache_returns_fresh(self):
        fresh = pd.DataFrame({"Date": [pd.Timestamp("2024-01-02")], "Close": [100.0]})
        result = _merge_frames(None, fresh)
        pd.testing.assert_frame_equal(result, fresh)

    def test_no_overlap_appends_and_sorts(self):
        cached = pd.DataFrame({
            "Date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
            "Close": [100.0, 101.0],
        })
        fresh = pd.DataFrame({"Date": [pd.Timestamp("2024-01-03")], "Close": [102.0]})
        result = _merge_frames(cached, fresh)
        assert list(result["Date"]) == [
            pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"),
        ]
        assert list(result["Close"]) == [100.0, 101.0, 102.0]

    def test_overlapping_dates_fresh_wins(self):
        cached = pd.DataFrame({
            "Date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
            "Close": [100.0, 999.0],
        })
        fresh = pd.DataFrame({
            "Date": [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")],
            "Close": [101.0, 102.0],
        })
        result = _merge_frames(cached, fresh)
        assert list(result["Date"]) == [
            pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"),
        ]
        assert list(result["Close"]) == [100.0, 101.0, 102.0]

    def test_empty_fresh_returns_cached(self):
        cached = pd.DataFrame({"Date": [pd.Timestamp("2024-01-01")], "Close": [100.0]})
        fresh = pd.DataFrame(columns=["Date", "Close"])
        result = _merge_frames(cached, fresh)
        pd.testing.assert_frame_equal(result, cached)
