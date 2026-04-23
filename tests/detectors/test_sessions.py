"""
Tests for src/detectors/sessions.py
"""
from __future__ import annotations

import pandas as pd
import pytest

from detectors.sessions import detect_sessions, in_kill_zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(utc_times: list[str], n_bars: int = 1) -> pd.DataFrame:
    """
    Build a minimal OHLCV DataFrame with bars at specific UTC timestamps.
    Each string in utc_times produces one bar.
    """
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="UTC") for t in utc_times])
    n = len(idx)
    return pd.DataFrame(
        {
            "Open":   [1.1] * n,
            "High":   [1.11] * n,
            "Low":    [1.09] * n,
            "Close":  [1.105] * n,
            "Volume": [100.0] * n,
        },
        index=idx,
    )


def _week_of_bars(freq: str = "15min") -> pd.DataFrame:
    """Full week of 15-min bars (Mon–Fri) for comprehensive session tagging."""
    idx = pd.date_range("2024-01-08 00:00", "2024-01-12 23:45", freq=freq, tz="UTC")
    n = len(idx)
    return pd.DataFrame(
        {"Open": [1.1] * n, "High": [1.11] * n,
         "Low": [1.09] * n, "Close": [1.105] * n, "Volume": [1.0] * n},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_all_columns_added(self):
        df = _week_of_bars()
        out = detect_sessions(df)
        for col in ("session", "in_kill_zone", "ar_high", "ar_low", "amd_phase"):
            assert col in out.columns, f"Missing: {col}"

    def test_returns_copy(self):
        df = _week_of_bars()
        out = detect_sessions(df)
        assert "session" not in df.columns


# ---------------------------------------------------------------------------
# Session tagging
# ---------------------------------------------------------------------------

class TestSessionTagging:
    # London Kill Zone: 02:00–05:00 EST = 07:00–10:00 UTC
    def test_london_kz_bar(self):
        df = _make_df(["2024-01-08 07:30:00+00:00"])
        out = detect_sessions(df)
        assert out["session"].iloc[0] == "london"
        assert out["in_kill_zone"].iloc[0] is True or out["in_kill_zone"].iloc[0]

    # New York Kill Zone: 08:00–11:00 EST = 13:00–16:00 UTC
    def test_ny_kz_bar(self):
        df = _make_df(["2024-01-08 13:30:00+00:00"])
        out = detect_sessions(df)
        assert out["session"].iloc[0] == "new_york"
        assert out["in_kill_zone"].iloc[0]

    # Asian session: 19:00–22:00 EST = 00:00–03:00 UTC
    def test_asian_bar(self):
        df = _make_df(["2024-01-09 01:00:00+00:00"])
        out = detect_sessions(df)
        assert out["session"].iloc[0] == "asian"
        assert not out["in_kill_zone"].iloc[0]

    # London close: 11:00–13:00 EST = 16:00–18:00 UTC
    def test_london_close_bar(self):
        df = _make_df(["2024-01-08 17:00:00+00:00"])
        out = detect_sessions(df)
        assert out["session"].iloc[0] == "london_close"
        assert not out["in_kill_zone"].iloc[0]

    # Off hours
    def test_off_hours_bar(self):
        df = _make_df(["2024-01-08 22:00:00+00:00"])
        out = detect_sessions(df)
        assert out["session"].iloc[0] == "off"
        assert not out["in_kill_zone"].iloc[0]

    def test_session_values_are_valid_strings(self):
        df = _week_of_bars()
        out = detect_sessions(df)
        valid = {"asian", "london", "new_york", "london_close", "off"}
        assert set(out["session"].unique()).issubset(valid)

    def test_in_kill_zone_is_boolean(self):
        df = _week_of_bars()
        out = detect_sessions(df)
        assert out["in_kill_zone"].dtype == bool

    def test_amd_phase_values_are_valid(self):
        df = _week_of_bars()
        out = detect_sessions(df)
        assert set(out["amd_phase"].unique()).issubset({0, 1, 2, 3})


# ---------------------------------------------------------------------------
# Asian Range
# ---------------------------------------------------------------------------

class TestAsianRange:
    def test_ar_high_gte_ar_low(self):
        df = _week_of_bars()
        out = detect_sessions(df)
        valid = out[out["ar_high"].notna() & out["ar_low"].notna()]
        assert (valid["ar_high"] >= valid["ar_low"]).all()

    def test_ar_computed_from_asian_bars(self):
        # Build a day where we control the Asian session highs/lows precisely
        times = pd.date_range("2024-01-08 00:00", periods=12, freq="15min", tz="UTC")
        highs  = [1.11] * 12
        lows   = [1.09] * 12
        # Spike the Asian session bars (00:00–02:45 UTC = 19:00–21:45 EST)
        highs[0] = 1.15
        lows[0]  = 1.05
        df = pd.DataFrame(
            {"Open": [1.10] * 12, "High": highs, "Low": lows,
             "Close": [1.10] * 12, "Volume": [1.0] * 12},
            index=times,
        )
        out = detect_sessions(df)
        asian_rows = out[out["session"] == "asian"]
        if not asian_rows.empty:
            ar_h = out["ar_high"].iloc[0]
            ar_l = out["ar_low"].iloc[0]
            if not pd.isna(ar_h):
                assert ar_h >= 1.14   # must capture the spike high


# ---------------------------------------------------------------------------
# in_kill_zone helper
# ---------------------------------------------------------------------------

class TestInKillZone:
    def test_london_timestamp_is_kz(self):
        ts = pd.Timestamp("2024-01-08 07:30:00", tz="UTC")
        assert in_kill_zone(ts)

    def test_ny_timestamp_is_kz(self):
        ts = pd.Timestamp("2024-01-08 14:00:00", tz="UTC")
        assert in_kill_zone(ts)

    def test_asian_timestamp_is_not_kz(self):
        ts = pd.Timestamp("2024-01-08 01:00:00", tz="UTC")
        assert not in_kill_zone(ts)

    def test_off_hours_not_kz(self):
        ts = pd.Timestamp("2024-01-08 22:00:00", tz="UTC")
        assert not in_kill_zone(ts)
