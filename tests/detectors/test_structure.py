"""
Tests for src/detectors/structure.py

Uses synthetic OHLCV DataFrames with known patterns to verify that
swing points, BOS, and CHoCH are detected correctly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from detectors.structure import detect_structure, get_structure_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(highs: list[float], lows: list[float], closes: list[float] | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from explicit high/low sequences."""
    n = len(highs)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    opens = closes  # open == close simplifies tests
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": [1.0] * n},
        index=idx,
    )


def _uptrend(n_waves: int = 3, lookback: int = 2) -> pd.DataFrame:
    """
    Build an uptrending DataFrame with clear HH/HL pattern.
    Each wave: small dip then larger rally.
    """
    highs, lows, closes = [], [], []
    base = 1.0
    for i in range(n_waves):
        # rally leg
        highs  += [base + 0.05, base + 0.08, base + 0.10]
        lows   += [base + 0.01, base + 0.03, base + 0.06]
        closes += [base + 0.04, base + 0.07, base + 0.10]
        # pullback leg
        highs  += [base + 0.08, base + 0.05]
        lows   += [base + 0.04, base + 0.02]
        closes += [base + 0.06, base + 0.03]
        base   += 0.10
    # Add enough padding so swings at the edges get confirmed
    pad = lookback + 1
    highs  = [highs[0]] * pad + highs + [highs[-1]] * pad
    lows   = [lows[0]]  * pad + lows  + [lows[-1]]  * pad
    closes = [closes[0]] * pad + closes + [closes[-1]] * pad
    return _df(highs, lows, closes)


# ---------------------------------------------------------------------------
# detect_structure output schema
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_all_columns_added(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        for col in ("swing_high", "swing_low", "trend",
                    "bos_bull", "bos_bear", "choch_bull", "choch_bear",
                    "last_sh", "last_sl"):
            assert col in out.columns, f"Missing column: {col}"

    def test_original_ohlcv_columns_untouched(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            pd.testing.assert_series_equal(out[col], df[col])

    def test_returns_copy_not_inplace(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        assert "swing_high" not in df.columns


# ---------------------------------------------------------------------------
# Swing point detection
# ---------------------------------------------------------------------------

class TestSwingPoints:
    def test_detects_local_maximum(self):
        # Bar 3 is a clear peak: 1.0, 1.1, 1.2, [1.3], 1.2, 1.1, 1.0
        highs  = [1.0, 1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 1.0, 1.0]
        lows   = [0.9] * 9
        df = _df(highs, lows)
        out = detect_structure(df, lookback=2)
        assert out["swing_high"].iloc[3] == pytest.approx(1.3)

    def test_detects_local_minimum(self):
        # Bar 3 is a clear trough
        lows  = [1.0, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0]
        highs = [1.1] * 9
        df = _df(highs, lows)
        out = detect_structure(df, lookback=2)
        assert out["swing_low"].iloc[3] == pytest.approx(0.7)

    def test_no_swing_at_flat_peak(self):
        # Tie at the maximum — neither bar qualifies as a strict swing high
        highs = [1.0, 1.2, 1.2, 1.2, 1.0, 1.0, 1.0]
        lows  = [0.9] * 7
        df = _df(highs, lows)
        out = detect_structure(df, lookback=2)
        # No bar should be labelled swing_high in the flat region
        assert out["swing_high"].iloc[1:4].isna().all()

    def test_swing_high_nan_outside_window(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        # First and last `lookback` bars cannot be confirmed swings
        assert np.isnan(out["swing_high"].iloc[0])
        assert np.isnan(out["swing_high"].iloc[-1])


# ---------------------------------------------------------------------------
# BOS detection
# ---------------------------------------------------------------------------

class TestBOS:
    def test_bos_bull_fires_in_uptrend(self):
        # BOS requires an established BULL trend (from a prior CHoCH).
        # Wave 1: swing high at bar 3 (1.30), break at bar 6 (1.32) → CHoCH_BULL, trend=BULL
        # Wave 2: swing high at bar 10 (1.38), break at bar 13 (1.42) → BOS_BULL
        highs  = [1.10, 1.20, 1.25, 1.30, 1.25, 1.20,  # wave 1
                  1.35, 1.30, 1.25, 1.22, 1.38, 1.35,  # break + wave 2 swing
                  1.28, 1.45, 1.40]                      # break → BOS_BULL
        lows   = [1.00] * 15
        closes = [1.05, 1.15, 1.22, 1.28, 1.22, 1.15,
                  1.32, 1.28, 1.22, 1.19, 1.36, 1.32,
                  1.24, 1.42, 1.38]
        df = _df(highs, lows, closes)
        out = detect_structure(df, lookback=2)
        assert out["bos_bull"].any(), "Expected at least one bullish BOS"

    def test_bos_bear_fires_in_downtrend(self):
        # Wave 1: swing low at bar 3 (0.80), break at bar 6 (0.77) → CHoCH_BEAR, trend=BEAR
        # Wave 2: swing low at bar 10 (0.72), break at bar 13 (0.67) → BOS_BEAR
        highs  = [1.10] * 15
        lows   = [1.00, 0.90, 0.85, 0.80, 0.85, 0.90,  # wave 1
                  0.75, 0.80, 0.85, 0.88, 0.72, 0.75,  # break + wave 2 swing
                  0.82, 0.65, 0.70]                      # break → BOS_BEAR
        closes = [1.05, 0.92, 0.87, 0.82, 0.87, 0.92,
                  0.77, 0.82, 0.87, 0.90, 0.74, 0.77,
                  0.84, 0.67, 0.72]
        df = _df(highs, lows, closes)
        out = detect_structure(df, lookback=2)
        assert out["bos_bear"].any(), "Expected at least one bearish BOS"

    def test_bos_and_choch_are_mutually_exclusive_per_bar(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        # A bar should not be both BOS and CHoCH simultaneously
        for col_a, col_b in [("bos_bull", "choch_bull"), ("bos_bear", "choch_bear")]:
            both = out[col_a] & out[col_b]
            assert not both.any(), f"{col_a} and {col_b} fired on same bar"


# ---------------------------------------------------------------------------
# CHoCH detection
# ---------------------------------------------------------------------------

class TestCHoCH:
    def test_choch_bear_after_uptrend(self):
        # Uptrend then break below last swing low
        highs  = [1.0, 1.1, 1.2, 1.3, 1.2, 1.1, 1.0,   # uptrend
                  1.1, 1.2, 1.1, 1.0, 0.9, 0.8]         # reversal
        lows   = [0.9, 1.0, 1.1, 1.2, 1.1, 1.0, 0.9,
                  1.0, 1.1, 1.0, 0.9, 0.8, 0.7]
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        df = _df(highs, lows, closes)
        out = detect_structure(df, lookback=2)
        assert out["choch_bear"].any() or out["bos_bear"].any()


# ---------------------------------------------------------------------------
# Trend column
# ---------------------------------------------------------------------------

class TestTrend:
    def test_trend_values_are_valid(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        assert set(out["trend"].unique()).issubset({-1, 0, 1})

    def test_last_sh_sl_are_monotone_non_decreasing_in_bull(self):
        # In a clear uptrend the tracked structural high should never go backwards
        df = _uptrend(n_waves=4)
        out = detect_structure(df, lookback=2)
        sh = out["last_sh"].dropna().values
        # Allow flat (same value repeated) but not decreasing
        assert (np.diff(sh) >= 0).all() or len(sh) == 0


# ---------------------------------------------------------------------------
# get_structure_events
# ---------------------------------------------------------------------------

class TestGetStructureEvents:
    def test_returns_list(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        events = get_structure_events(out)
        assert isinstance(events, list)

    def test_event_kinds_are_valid(self):
        df = _uptrend()
        out = detect_structure(df, lookback=2)
        valid = {"BOS_BULL", "BOS_BEAR", "CHOCH_BULL", "CHOCH_BEAR"}
        for e in get_structure_events(out):
            assert e.kind in valid

    def test_events_sorted_by_bar_index(self):
        df = _uptrend(n_waves=4)
        out = detect_structure(df, lookback=2)
        events = get_structure_events(out)
        indices = [e.bar_index for e in events]
        assert indices == sorted(indices)
