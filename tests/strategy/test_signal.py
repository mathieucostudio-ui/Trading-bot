"""
Tests for src/strategy/signal.py
"""
from __future__ import annotations

import pandas as pd
import pytest

from strategy.signal import TradeSignal, generate_signals, filter_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enriched_df(
    n: int = 20,
    *,
    in_kill_zone: bool = False,
    amd_phase: int = 0,
) -> pd.DataFrame:
    """Minimal enriched DataFrame with all required columns."""
    idx = pd.date_range("2024-01-08 08:00", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "Open": [1.1] * n, "High": [1.1] * n,
        "Low":  [1.0] * n, "Close": [1.05] * n, "Volume": [1.0] * n,
        "in_kill_zone": [in_kill_zone] * n,
        "sweep_bull":   [False] * n,
        "sweep_bear":   [False] * n,
        "bos_bull":     [False] * n,
        "bos_bear":     [False] * n,
        "choch_bull":   [False] * n,
        "choch_bear":   [False] * n,
        "ob_bull":      [False] * n,
        "ob_bear":      [False] * n,
        "fvg_bull":     [False] * n,
        "fvg_bear":     [False] * n,
        "amd_phase":    [amd_phase] * n,
    }, index=idx)
    return df


def _full_long_signal_df(n: int = 10) -> pd.DataFrame:
    """All five long factors active, KZ=True, AMD phase=3."""
    df = _enriched_df(n, in_kill_zone=True, amd_phase=3)
    df["sweep_bull"] = True
    df["bos_bull"]   = True
    df["choch_bull"] = True
    df["ob_bull"]    = True
    return df


def _full_short_signal_df(n: int = 10) -> pd.DataFrame:
    """All five short factors active, KZ=True, AMD phase=3."""
    df = _enriched_df(n, in_kill_zone=True, amd_phase=3)
    df["sweep_bear"] = True
    df["bos_bear"]   = True
    df["choch_bear"] = True
    df["ob_bear"]    = True
    return df


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_returns_list(self):
        df = _enriched_df()
        result = generate_signals(df, require_kill_zone=False, require_amd_phase3=False)
        assert isinstance(result, list)

    def test_all_items_are_tradesignals(self):
        df = _full_long_signal_df()
        result = generate_signals(df)
        assert all(isinstance(s, TradeSignal) for s in result)

    def test_requires_pipeline_columns(self):
        df = pd.DataFrame({"Close": [1.0]})
        with pytest.raises(ValueError, match="Missing columns"):
            generate_signals(df)

    def test_sorted_by_bar_index(self):
        df = _full_long_signal_df(20)
        signals = generate_signals(df)
        indices = [s.bar_index for s in signals]
        assert indices == sorted(indices)


# ---------------------------------------------------------------------------
# Filtering: Kill Zone and AMD phase
# ---------------------------------------------------------------------------

class TestFilters:
    def test_no_signals_outside_kill_zone_when_required(self):
        df = _full_long_signal_df()
        df["in_kill_zone"] = False
        signals = generate_signals(df, require_kill_zone=True)
        assert len(signals) == 0

    def test_signals_fire_outside_kill_zone_when_not_required(self):
        df = _full_long_signal_df()
        df["in_kill_zone"] = False
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=False)
        assert len(signals) > 0

    def test_no_signals_outside_amd_phase3_when_required(self):
        df = _full_long_signal_df()
        df["amd_phase"] = 1   # Accumulation phase
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=True)
        assert len(signals) == 0

    def test_signals_fire_in_phase3(self):
        df = _full_long_signal_df()
        df["amd_phase"] = 3
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=True)
        assert len(signals) > 0

    def test_missing_amd_phase_column_handled(self):
        df = _full_long_signal_df()
        df = df.drop(columns=["amd_phase"])
        # Should not raise; phase defaults to 0
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=False)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# Min score threshold
# ---------------------------------------------------------------------------

class TestMinScore:
    def test_min_score_4_filters_weak_signals(self):
        df = _enriched_df(5, in_kill_zone=True, amd_phase=3)
        # Only 2 long factors active → score = 2
        df["sweep_bull"] = True
        df["ob_bull"]    = True
        signals = generate_signals(df, min_score=4, require_kill_zone=False, require_amd_phase3=False)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) == 0

    def test_min_score_1_allows_weak_signals(self):
        df = _enriched_df(5, in_kill_zone=True, amd_phase=3)
        df["sweep_bull"] = True   # 1 factor
        signals = generate_signals(
            df, min_score=1, require_kill_zone=False, require_amd_phase3=False
        )
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) > 0


# ---------------------------------------------------------------------------
# Signal fields
# ---------------------------------------------------------------------------

class TestSignalFields:
    def test_long_signal_direction(self):
        df = _full_long_signal_df(5)
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=False)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) > 0

    def test_entry_price_equals_close(self):
        df = _full_long_signal_df(5)
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=False)
        close_arr = df["Close"].values
        for sig in signals:
            assert sig.entry_price == pytest.approx(close_arr[sig.bar_index])

    def test_score_is_positive(self):
        df = _full_long_signal_df(5)
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=False, min_score=1)
        for sig in signals:
            assert sig.confluence_score > 0

    def test_short_signal_fires_from_bear_factors(self):
        df = _full_short_signal_df(5)
        signals = generate_signals(df, require_kill_zone=False, require_amd_phase3=False)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) > 0


# ---------------------------------------------------------------------------
# filter_signals
# ---------------------------------------------------------------------------

class TestFilterSignals:
    def _get_both(self) -> list[TradeSignal]:
        # Generate a mix of long and short signals
        df = _enriched_df(5, in_kill_zone=True, amd_phase=3)
        df["sweep_bull"] = True
        df["sweep_bear"] = True
        return generate_signals(df, min_score=1, require_kill_zone=False, require_amd_phase3=False)

    def test_filter_by_direction_long(self):
        signals = self._get_both()
        long_only = filter_signals(signals, direction="long")
        assert all(s.direction == "long" for s in long_only)

    def test_filter_by_direction_short(self):
        signals = self._get_both()
        short_only = filter_signals(signals, direction="short")
        assert all(s.direction == "short" for s in short_only)

    def test_filter_by_min_score(self):
        df = _full_long_signal_df(5)
        signals = generate_signals(df, min_score=1, require_kill_zone=False, require_amd_phase3=False)
        filtered = filter_signals(signals, min_score=3)
        assert all(s.confluence_score >= 3 for s in filtered)
