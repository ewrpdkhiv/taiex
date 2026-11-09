import pandas as pd

from scripts.generate_static import _df_to_records, _fallback_days, _recovery_days


def _df(closes):
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "Close": closes,
        }
    )


class TestDaysUntilCross:
    def test_recovery_counts_trading_days_until_back_above(self):
        full = _df([100, 90, 95, 99, 101])
        assert _recovery_days(full["Date"][1], 100.0, full) == 3

    def test_recovery_none_when_never_back(self):
        full = _df([100, 90, 95])
        assert _recovery_days(full["Date"][1], 100.0, full) is None

    def test_fallback_counts_trading_days_until_back_below(self):
        full = _df([100, 110, 105, 100, 120])
        assert _fallback_days(full["Date"][1], 100.0, full) == 2

    def test_fallback_none_when_never_back(self):
        full = _df([100, 110, 105, 101])
        assert _fallback_days(full["Date"][1], 100.0, full) is None


class TestDfToRecords:
    def _rows(self, full, idx):
        rows = full.iloc[[idx]].copy()
        rows["prev_close"] = full["Close"][idx - 1]
        rows["change_pct"] = (rows["Close"] / rows["prev_close"] - 1) * 100
        return rows

    def test_gain_kind_adds_fallback_days(self):
        full = _df([100, 110, 105, 100])
        rec = _df_to_records(self._rows(full, 1), full, "gain")[0]
        assert rec["fallback_days"] == 2
        assert rec["recovery_days"] is None

    def test_drop_kind_has_no_fallback_field(self):
        full = _df([100, 90, 100])
        rec = _df_to_records(self._rows(full, 1), full, "drop")[0]
        assert rec["recovery_days"] == 1
        assert "fallback_days" not in rec
