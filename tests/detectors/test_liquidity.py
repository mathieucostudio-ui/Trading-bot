"""
Tests for src/detectors/liquidity.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from detectors.structure import detect_structure
from detectors.liquidity import LiquidityPool, detect_liquidity, get_unswept_pools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(highs, lows, closes=None) -> pd.DataFrame:
    n = len(highs)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    idx = pd.date_range("2024-01-08", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows,
         "Close": closes, "Volume": [1.0] * n},
        index=idx,
    )


def _structured(highs, lows, closes=None, lookback=2) -> pd.DataFrame:
    """Return a DataFrame that has already been through detect_structure."""
    df = _df(highs, lows, closes)
    return detect_structure(df, lookback=lookback)


def _two_swing_highs_equal() -> pd.DataFrame:
    """
    Create two swing highs at approximately the same price level (≈1.20)
    to form an EQH cluster.

    Pattern (lookback=2):
      bars 0-1: rising into swing high at bar 2 (high=1.20)
      bars 3-4: pullback
      bars 5-6: rising into second swing high at bar 7 (high=1.201)
      bars 8-9: padding for confirmation
    """
    highs  = [1.10, 1.15, 1.20, 1.15, 1.10, 1.15, 1.18, 1.201, 1.18, 1.15]
    lows   = [1.05, 1.08, 1.12, 1.08, 1.05, 1.08, 1.12, 1.15,  1.12, 1.08]
    return _structured(highs, lows)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_columns_added(self):
        df = _structured(
            [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2],
            [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1],
        )
        out, _ = detect_liquidity(df)
        for col in ("bsl", "ssl", "eqh", "eql", "sweep_bull", "sweep_bear"):
            assert col in out.columns, f"Missing column: {col}"

    def test_requires_structure_columns(self):
        df = _df([1.1, 1.2], [1.0, 1.1])
        with pytest.raises(ValueError, match="swing_high"):
            detect_liquidity(df)

    def test_returns_list_of_pools(self):
        df = _structured(
            [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2],
            [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1],
        )
        _, pools = detect_liquidity(df)
        assert isinstance(pools, list)
        assert all(isinstance(p, LiquidityPool) for p in pools)


# ---------------------------------------------------------------------------
# BSL / SSL pools
# ---------------------------------------------------------------------------

class TestBSLSSL:
    def test_bsl_pools_exist_when_swing_highs_present(self):
        highs = [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2]
        lows  = [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1]
        df = _structured(highs, lows)
        _, pools = detect_liquidity(df)
        bsl = [p for p in pools if p.kind == "bsl"]
        assert len(bsl) > 0

    def test_ssl_pools_exist_when_swing_lows_present(self):
        highs = [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2]
        lows  = [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1]
        df = _structured(highs, lows)
        _, pools = detect_liquidity(df)
        ssl = [p for p in pools if p.kind == "ssl"]
        assert len(ssl) > 0

    def test_bsl_levels_are_above_ssl_levels(self):
        highs = [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2]
        lows  = [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1]
        df = _structured(highs, lows)
        out, pools = detect_liquidity(df)
        bsl_vals = [p.level for p in pools if p.kind == "bsl"]
        ssl_vals = [p.level for p in pools if p.kind == "ssl"]
        if bsl_vals and ssl_vals:
            assert min(bsl_vals) > min(ssl_vals)


# ---------------------------------------------------------------------------
# Equal Highs / Equal Lows
# ---------------------------------------------------------------------------

class TestEqualHighsLows:
    def test_eqh_detected_when_two_swing_highs_close(self):
        df = _two_swing_highs_equal()
        _, pools = detect_liquidity(df, range_pct=0.005)
        eqh = [p for p in pools if p.kind == "eqh"]
        assert len(eqh) >= 1, "Expected at least one EQH cluster"

    def test_eqh_level_between_the_two_swing_highs(self):
        df = _two_swing_highs_equal()
        _, pools = detect_liquidity(df, range_pct=0.005)
        eqh = [p for p in pools if p.kind == "eqh"]
        if eqh:
            assert 1.19 < eqh[0].level < 1.21

    def test_no_eqh_when_highs_far_apart(self):
        # Two swing highs 5% apart — should NOT cluster
        highs  = [1.10, 1.15, 1.20, 1.15, 1.10, 1.15, 1.18, 1.26, 1.22, 1.18]
        lows   = [1.05, 1.08, 1.12, 1.08, 1.05, 1.08, 1.12, 1.18, 1.14, 1.10]
        df = _structured(highs, lows)
        _, pools = detect_liquidity(df, range_pct=0.001)  # tight threshold
        eqh = [p for p in pools if p.kind == "eqh"]
        assert len(eqh) == 0


# ---------------------------------------------------------------------------
# Sweep detection
# ---------------------------------------------------------------------------

class TestSweeps:
    def test_ssl_sweep_detected_as_bullish(self):
        """
        Build a clear SSL sweep: price wicks below a swing low then closes above it.
        Highs and lows chosen so swing low is at ~1.00, then bar wicks to 0.98 and
        closes at 1.02.
        """
        # Swing low forms at bar 2 (low=1.00, lower than neighbours)
        # Then at bar 7: low wicks to 0.98 < 1.00, but close=1.02 > 1.00
        highs  = [1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.10]
        lows   = [1.05, 1.02, 1.00, 1.02, 1.05, 1.04, 1.03, 0.98, 1.03, 1.04]
        closes = [1.08, 1.05, 1.03, 1.05, 1.08, 1.07, 1.06, 1.02, 1.06, 1.07]
        df = _structured(highs, lows, closes)
        out, pools = detect_liquidity(df)
        assert out["sweep_bull"].any(), "Expected a bullish sweep (SSL swept)"

    def test_bsl_sweep_detected_as_bearish(self):
        """
        Price wicks above a swing high then closes below it → bearish sweep.
        """
        highs  = [1.05, 1.08, 1.10, 1.08, 1.05, 1.06, 1.07, 1.12, 1.07, 1.06]
        lows   = [1.00, 1.02, 1.05, 1.02, 1.00, 1.01, 1.02, 1.04, 1.02, 1.01]
        closes = [1.03, 1.06, 1.08, 1.06, 1.03, 1.04, 1.05, 1.06, 1.05, 1.04]
        df = _structured(highs, lows, closes)
        out, pools = detect_liquidity(df)
        assert out["sweep_bear"].any(), "Expected a bearish sweep (BSL swept)"


# ---------------------------------------------------------------------------
# get_unswept_pools
# ---------------------------------------------------------------------------

class TestGetUnsweptPools:
    def test_returns_only_unswept(self):
        highs = [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2]
        lows  = [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1]
        df = _structured(highs, lows)
        _, pools = detect_liquidity(df)
        unswept = get_unswept_pools(pools)
        assert all(not p.swept for p in unswept)

    def test_kind_filter(self):
        highs = [1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.2]
        lows  = [1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1]
        df = _structured(highs, lows)
        _, pools = detect_liquidity(df)
        bsl_only = get_unswept_pools(pools, kind="bsl")
        assert all(p.kind == "bsl" for p in bsl_only)
