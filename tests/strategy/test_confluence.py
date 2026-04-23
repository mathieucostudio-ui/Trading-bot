"""
Tests for src/strategy/confluence.py
"""
from __future__ import annotations

import pandas as pd
import pytest

from detectors import run_pipeline
from strategy.confluence import (
    ConfluenceScore,
    score_confluence,
    add_confluence_columns,
    _require_columns,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_enriched_df(n: int = 20) -> pd.DataFrame:
    """
    Build a minimal DataFrame that already has all columns the confluence scorer
    requires, without running the full pipeline (fast, no network).
    """
    import numpy as np
    idx = pd.date_range("2024-01-08 08:00", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "Open":  [1.1] * n,
        "High":  [1.1] * n,
        "Low":   [1.0] * n,
        "Close": [1.05] * n,
        "Volume": [1.0] * n,
        # Required confluence columns — all False / 0 by default
        "in_kill_zone": [False] * n,
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
    }, index=idx)
    return df


def _all_long_factors(n: int = 10) -> pd.DataFrame:
    """DataFrame where every bar has all five long factors active."""
    df = _minimal_enriched_df(n)
    df["in_kill_zone"] = True
    df["sweep_bull"]   = True
    df["bos_bull"]     = True
    df["choch_bull"]   = True
    df["ob_bull"]      = True
    return df


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_returns_list_of_confluencescores(self):
        df = _minimal_enriched_df()
        result = score_confluence(df)
        assert isinstance(result, list)
        assert all(isinstance(s, ConfluenceScore) for s in result)

    def test_length_equals_dataframe_length(self):
        n = 15
        df = _minimal_enriched_df(n)
        result = score_confluence(df)
        assert len(result) == n

    def test_bar_index_sequential(self):
        df = _minimal_enriched_df(8)
        result = score_confluence(df)
        assert [s.bar_index for s in result] == list(range(8))

    def test_add_confluence_columns_adds_columns(self):
        df = _minimal_enriched_df()
        out = add_confluence_columns(df)
        assert "long_score" in out.columns
        assert "short_score" in out.columns

    def test_add_confluence_columns_returns_copy(self):
        df = _minimal_enriched_df()
        _ = add_confluence_columns(df)
        assert "long_score" not in df.columns

    def test_requires_pipeline_columns(self):
        df = pd.DataFrame({"Close": [1.0]})
        with pytest.raises(ValueError, match="Missing columns"):
            score_confluence(df)


# ---------------------------------------------------------------------------
# Score range
# ---------------------------------------------------------------------------

class TestScoreRange:
    def test_all_zeros_when_no_factors(self):
        df = _minimal_enriched_df(5)
        scores = score_confluence(df)
        assert all(s.long_score == 0 for s in scores)
        assert all(s.short_score == 0 for s in scores)

    def test_max_score_is_5(self):
        df = _all_long_factors(5)
        scores = score_confluence(df)
        assert all(s.long_score == 5 for s in scores)

    def test_score_bounded_0_to_5(self):
        df = _all_long_factors(5)
        scores = score_confluence(df)
        for s in scores:
            assert 0 <= s.long_score <= 5
            assert 0 <= s.short_score <= 5


# ---------------------------------------------------------------------------
# Individual factors
# ---------------------------------------------------------------------------

class TestFactors:
    def test_kill_zone_contributes_1(self):
        df = _minimal_enriched_df(5)
        df["in_kill_zone"] = True
        scores = score_confluence(df)
        assert all(s.long_score == 1 for s in scores)
        assert all(s.short_score == 1 for s in scores)

    def test_sweep_bull_contributes_to_long(self):
        df = _minimal_enriched_df(5)
        df["sweep_bull"] = True
        scores = score_confluence(df)
        assert all(s.long_score >= 1 for s in scores)
        assert all(s.short_score == 0 for s in scores)

    def test_sweep_bear_contributes_to_short(self):
        df = _minimal_enriched_df(5)
        df["sweep_bear"] = True
        scores = score_confluence(df)
        assert all(s.short_score >= 1 for s in scores)
        assert all(s.long_score == 0 for s in scores)

    def test_choch_bull_counted_as_both_displacement_and_choch(self):
        """A choch_bull bar contributes 2 to long_score (disp + choch)."""
        df = _minimal_enriched_df(5)
        # Place choch_bull only on bar 4 (last bar in any window of size >= 1)
        df["choch_bull"] = [False, False, False, False, True]
        scores = score_confluence(df, lookback=1)
        # Bar 4: choch_bull in window → has_displacement=True, has_choch=True → +2
        assert scores[4].long_score == 2

    def test_ob_bull_contributes_to_long(self):
        df = _minimal_enriched_df(3)
        df["ob_bull"] = True
        scores = score_confluence(df, lookback=1)
        assert all(s.long_score >= 1 for s in scores)

    def test_fvg_bear_contributes_to_short(self):
        df = _minimal_enriched_df(3)
        df["fvg_bear"] = True
        scores = score_confluence(df, lookback=1)
        assert all(s.short_score >= 1 for s in scores)


# ---------------------------------------------------------------------------
# Lookback window behaviour
# ---------------------------------------------------------------------------

class TestLookbackWindow:
    def test_lookback_1_only_current_bar(self):
        """With lookback=1, only the current bar's signals count."""
        df = _minimal_enriched_df(5)
        # bos_bull only on bar 0
        df.loc[df.index[0], "bos_bull"] = True
        scores = score_confluence(df, lookback=1)
        # Only bar 0 should have the displacement score
        assert scores[0].long_score == 1
        assert scores[1].long_score == 0

    def test_lookback_carries_event_forward(self):
        """With lookback=3, a bos_bull at bar 0 should still count for bars 1 and 2."""
        df = _minimal_enriched_df(5)
        df.loc[df.index[0], "bos_bull"] = True
        scores = score_confluence(df, lookback=3)
        assert scores[0].long_score >= 1
        assert scores[1].long_score >= 1
        assert scores[2].long_score >= 1
        # Bar 3 is just outside the window for bar 0's event
        assert scores[3].long_score == 0


# ---------------------------------------------------------------------------
# Direction property
# ---------------------------------------------------------------------------

class TestDirectionProperty:
    def test_direction_long_when_long_higher(self):
        df = _minimal_enriched_df(3)
        df["sweep_bull"] = True
        scores = score_confluence(df, lookback=1)
        assert scores[0].direction == "long"

    def test_direction_short_when_short_higher(self):
        df = _minimal_enriched_df(3)
        df["sweep_bear"] = True
        scores = score_confluence(df, lookback=1)
        assert scores[0].direction == "short"

    def test_direction_none_when_equal(self):
        df = _minimal_enriched_df(3)
        # Equal scores: both bull and bear active
        df["sweep_bull"] = True
        df["sweep_bear"] = True
        scores = score_confluence(df, lookback=1)
        assert scores[0].direction is None
