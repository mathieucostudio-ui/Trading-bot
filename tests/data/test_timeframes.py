"""
Unit tests for src/data/timeframes.py
"""

from __future__ import annotations

import pandas as pd
import pytest

from data.timeframes import align_to_htf_close, build_mtf, resample


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int, freq: str = "15min") -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 00:00", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "Open":   [1.1000 + i * 0.0001 for i in range(n)],
            "High":   [1.1010 + i * 0.0001 for i in range(n)],
            "Low":    [1.0990 + i * 0.0001 for i in range(n)],
            "Close":  [1.1005 + i * 0.0001 for i in range(n)],
            "Volume": [float(i + 1) for i in range(n)],
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# resample
# ---------------------------------------------------------------------------

class TestResample:
    def test_raises_on_unknown_tf(self):
        df = _make_ohlcv(20)
        with pytest.raises(ValueError, match="Unknown timeframe"):
            resample(df, "99x")

    def test_15m_to_1h_reduces_rows(self):
        df = _make_ohlcv(48)  # 48 × 15m = 12 hours
        h1 = resample(df, "1h")
        # 12 hours → at most 12 rows
        assert len(h1) <= 12

    def test_ohlcv_columns_preserved(self):
        df = _make_ohlcv(32)
        h1 = resample(df, "1h")
        assert list(h1.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_open_is_first_of_period(self):
        df = _make_ohlcv(4, freq="15min")  # 4 × 15m = 1 hour
        h1 = resample(df, "1h")
        assert h1["Open"].iloc[0] == pytest.approx(df["Open"].iloc[0])

    def test_close_is_last_of_period(self):
        df = _make_ohlcv(4, freq="15min")
        h1 = resample(df, "1h")
        assert h1["Close"].iloc[0] == pytest.approx(df["Close"].iloc[3])

    def test_high_is_max_of_period(self):
        df = _make_ohlcv(4, freq="15min")
        h1 = resample(df, "1h")
        assert h1["High"].iloc[0] == pytest.approx(df["High"].iloc[:4].max())

    def test_low_is_min_of_period(self):
        df = _make_ohlcv(4, freq="15min")
        h1 = resample(df, "1h")
        assert h1["Low"].iloc[0] == pytest.approx(df["Low"].iloc[:4].min())

    def test_volume_is_sum_of_period(self):
        df = _make_ohlcv(4, freq="15min")
        h1 = resample(df, "1h")
        assert h1["Volume"].iloc[0] == pytest.approx(df["Volume"].iloc[:4].sum())

    def test_no_nan_rows_in_output(self):
        df = _make_ohlcv(64)
        h4 = resample(df, "4h")
        assert not h4[["Open", "High", "Low", "Close"]].isna().any().any()

    def test_index_is_utc(self):
        df = _make_ohlcv(32)
        h1 = resample(df, "1h")
        assert h1.index.tzinfo is not None


# ---------------------------------------------------------------------------
# build_mtf
# ---------------------------------------------------------------------------

class TestBuildMtf:
    def test_returns_all_requested_tfs(self):
        df = _make_ohlcv(200)
        mtf = build_mtf(df, ["15m", "1h", "4h"])
        assert set(mtf.keys()) == {"15m", "1h", "4h"}

    def test_15m_passthrough_same_length(self):
        df = _make_ohlcv(200)
        mtf = build_mtf(df, ["15m", "1h"])
        # 15m entry should have same or close row count as original
        # (resampling at same freq can result in slight differences at boundaries)
        assert abs(len(mtf["15m"]) - len(df)) <= 1

    def test_htf_has_fewer_rows_than_ltf(self):
        df = _make_ohlcv(320)  # 320 × 15m = 80 hours
        mtf = build_mtf(df, ["15m", "1h", "4h"])
        assert len(mtf["1h"]) < len(mtf["15m"])
        assert len(mtf["4h"]) < len(mtf["1h"])


# ---------------------------------------------------------------------------
# align_to_htf_close
# ---------------------------------------------------------------------------

class TestAlignToHtfClose:
    def test_adds_htf_columns(self):
        ltf = _make_ohlcv(32, freq="15min")
        htf = resample(ltf, "1h")
        merged = align_to_htf_close(ltf, htf)
        for col in ("htf_open", "htf_high", "htf_low", "htf_close"):
            assert col in merged.columns

    def test_no_look_ahead_in_htf_close(self):
        ltf = _make_ohlcv(64, freq="15min")
        htf = resample(ltf, "1h")
        merged = align_to_htf_close(ltf, htf)
        # The first populated htf_close should not equal the FIRST hour's close —
        # it should reflect the PREVIOUS hour (shift(1) applied).
        # The very first rows will be NaN (no prior HTF bar) → ffill fills them eventually.
        # Verify that the htf_close at the start of hour 2 equals hour 1's close.
        hour1_close = htf["Close"].iloc[0]
        # Find first LTF bar that falls in hour 2
        hour2_start = htf.index[1]
        ltf_in_hour2 = merged[merged.index >= hour2_start]
        if not ltf_in_hour2.empty:
            assert ltf_in_hour2["htf_close"].iloc[0] == pytest.approx(hour1_close)

    def test_original_ltf_columns_untouched(self):
        ltf = _make_ohlcv(32, freq="15min")
        htf = resample(ltf, "1h")
        merged = align_to_htf_close(ltf, htf)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            pd.testing.assert_series_equal(merged[col], ltf[col])
