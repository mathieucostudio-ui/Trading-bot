"""
Tests pour src/backtest/walkforward.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestConfig
from backtest.walkforward import (
    WalkForwardResult,
    WalkForwardWindow,
    walk_forward,
    _build_windows,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_df(months: int = 12, freq: str = "1h") -> pd.DataFrame:
    """Série OHLCV synthétique couvrant `months` mois."""
    n_periods = months * 30 * (24 if freq == "1h" else 96)  # ~720 ou 2880 barres/mois
    idx = pd.date_range("2024-01-01 00:00", periods=n_periods, freq=freq, tz="UTC")

    rng = np.random.default_rng(7)
    price  = 1.10 + np.cumsum(rng.normal(0, 0.0003, n_periods))
    highs  = price + np.abs(rng.normal(0, 0.001, n_periods))
    lows   = price - np.abs(rng.normal(0, 0.001, n_periods))
    opens  = np.roll(price, 1); opens[0] = price[0]
    closes = price

    highs = np.maximum(highs, np.maximum(opens, closes))
    lows  = np.minimum(lows,  np.minimum(opens, closes))

    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows,
        "Close": closes, "Volume": [1.0] * n_periods,
    }, index=idx)


def _permissive_config() -> BacktestConfig:
    return BacktestConfig(
        structure_lookback=2,
        min_confluence_score=1,
        require_kill_zone=False,
        require_amd_phase3=False,
        confluence_lookback=2,
    )


# ---------------------------------------------------------------------------
# _build_windows
# ---------------------------------------------------------------------------

class TestBuildWindows:
    def test_returns_list(self):
        df = _synthetic_df(12)
        wins = _build_windows(df, is_months=6, oos_months=2)
        assert isinstance(wins, list)

    def test_windows_non_empty_for_long_series(self):
        df = _synthetic_df(12)
        wins = _build_windows(df, is_months=6, oos_months=2)
        assert len(wins) >= 1

    def test_is_and_oos_do_not_overlap(self):
        df = _synthetic_df(12)
        for is_start, is_end, oos_start, oos_end in _build_windows(df, 4, 2):
            assert oos_start > is_end

    def test_oos_end_within_df(self):
        df = _synthetic_df(12)
        df_end = df.index[-1]
        for _, _, _, oos_end in _build_windows(df, 4, 2):
            assert oos_end <= df_end

    def test_no_windows_when_data_too_short(self):
        df = _synthetic_df(3)   # 3 mois < IS(6) + OOS(2)
        wins = _build_windows(df, is_months=6, oos_months=2)
        assert len(wins) == 0


# ---------------------------------------------------------------------------
# walk_forward output schema
# ---------------------------------------------------------------------------

class TestWalkForwardSchema:
    def test_returns_walkforward_result(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        assert isinstance(res, WalkForwardResult)

    def test_windows_are_walkforwardwindow(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        assert all(isinstance(w, WalkForwardWindow) for w in res.windows)

    def test_config_preserved(self):
        df  = _synthetic_df(10, freq="1h")
        cfg = _permissive_config()
        res = walk_forward(df, is_months=4, oos_months=2, config=cfg)
        assert res.config is cfg

    def test_is_months_oos_months_preserved(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        assert res.is_months == 4
        assert res.oos_months == 2


# ---------------------------------------------------------------------------
# Fenêtres IS / OOS
# ---------------------------------------------------------------------------

class TestWindowContent:
    def test_each_window_has_is_and_oos_results(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        for w in res.windows:
            assert w.is_result is not None
            assert w.oos_result is not None

    def test_each_window_has_metrics(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        for w in res.windows:
            assert w.is_metrics is not None
            assert w.oos_metrics is not None

    def test_oos_equity_curve_not_empty(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        for w in res.windows:
            assert len(w.oos_result.equity_curve) > 0

    def test_window_ids_sequential(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        ids = [w.window_id for w in res.windows]
        assert ids == list(range(len(ids)))


# ---------------------------------------------------------------------------
# Propriétés agrégées
# ---------------------------------------------------------------------------

class TestAggregates:
    def test_avg_oos_win_rate_in_range(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        assert 0.0 <= res.avg_oos_win_rate <= 1.0

    def test_robustness_ratio_non_negative(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        for w in res.windows:
            assert w.robustness_ratio >= 0.0

    def test_summary_returns_string(self):
        df  = _synthetic_df(10, freq="1h")
        res = walk_forward(df, is_months=4, oos_months=2, config=_permissive_config())
        s = res.summary()
        assert isinstance(s, str)
        assert "Walk-Forward" in s

    def test_empty_result_when_no_windows(self):
        df  = _synthetic_df(3, freq="1h")
        res = walk_forward(df, is_months=6, oos_months=2, config=_permissive_config())
        assert res.windows == []
        assert res.avg_oos_win_rate == 0.0
