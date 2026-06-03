"""
Tests pour src/backtest/metrics.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import Trade
from backtest.metrics import MetricsResult, compute_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(pnl_val: float, direction: str = "long") -> Trade:
    """Crée un Trade avec un PnL connu via entry/exit prix cohérents."""
    entry = 1.10
    size  = 10_000.0
    if direction == "long":
        exit_price = entry + pnl_val / size
        sl = entry - 0.01
        tp = entry + 0.02
    else:
        exit_price = entry - pnl_val / size
        sl = entry + 0.01
        tp = entry - 0.02

    return Trade(
        direction=direction,
        entry_bar=1,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        size_units=size,
        signal_bar=0,
        exit_bar=5,
        exit_price=exit_price,
        exit_reason="tp" if pnl_val > 0 else "sl",
    )


def _all_winners(n: int = 10) -> list[Trade]:
    return [_make_trade(100.0) for _ in range(n)]


def _all_losers(n: int = 10) -> list[Trade]:
    return [_make_trade(-50.0) for _ in range(n)]


def _mixed(n_win: int = 6, n_lose: int = 4) -> list[Trade]:
    return [_make_trade(100.0)] * n_win + [_make_trade(-50.0)] * n_lose


# ---------------------------------------------------------------------------
# Cas limite : pas de trades
# ---------------------------------------------------------------------------

class TestEmptyTrades:
    def test_empty_returns_zero_metrics(self):
        m = compute_metrics([])
        assert m.total_trades == 0
        assert m.win_rate == 0.0
        assert m.total_pnl == 0.0
        assert m.sharpe_ratio == 0.0

    def test_returns_metrics_result(self):
        assert isinstance(compute_metrics([]), MetricsResult)


# ---------------------------------------------------------------------------
# Win rate
# ---------------------------------------------------------------------------

class TestWinRate:
    def test_all_winners(self):
        m = compute_metrics(_all_winners(10))
        assert m.win_rate == pytest.approx(1.0)

    def test_all_losers(self):
        m = compute_metrics(_all_losers(10))
        assert m.win_rate == pytest.approx(0.0)

    def test_mixed_60_pct(self):
        m = compute_metrics(_mixed(6, 4))
        assert m.win_rate == pytest.approx(0.6)

    def test_winning_losing_counts(self):
        m = compute_metrics(_mixed(7, 3))
        assert m.winning_trades == 7
        assert m.losing_trades  == 3
        assert m.total_trades   == 10


# ---------------------------------------------------------------------------
# PnL
# ---------------------------------------------------------------------------

class TestPnL:
    def test_total_pnl_all_winners(self):
        m = compute_metrics(_all_winners(5))
        assert m.total_pnl == pytest.approx(500.0)

    def test_total_pnl_mixed(self):
        # 6 × 100 + 4 × (-50) = 400
        m = compute_metrics(_mixed(6, 4))
        assert m.total_pnl == pytest.approx(400.0)

    def test_avg_trade_pnl(self):
        m = compute_metrics(_mixed(6, 4))
        assert m.avg_trade_pnl == pytest.approx(40.0)

    def test_total_return_pct(self):
        m = compute_metrics(_all_winners(10), initial_balance=10_000.0)
        assert m.total_return_pct == pytest.approx(0.10)   # 1000/10000

    def test_avg_winner_positive(self):
        m = compute_metrics(_mixed())
        assert m.avg_winner_pnl > 0

    def test_avg_loser_negative(self):
        m = compute_metrics(_mixed())
        assert m.avg_loser_pnl < 0


# ---------------------------------------------------------------------------
# Profit factor
# ---------------------------------------------------------------------------

class TestProfitFactor:
    def test_profit_factor_above_1_for_profitable(self):
        m = compute_metrics(_mixed(6, 4))
        # gross_profit=600, gross_loss=200 → PF=3
        assert m.profit_factor == pytest.approx(3.0)

    def test_profit_factor_inf_for_all_winners(self):
        m = compute_metrics(_all_winners())
        assert m.profit_factor == float("inf")

    def test_profit_factor_zero_for_all_losers(self):
        m = compute_metrics(_all_losers())
        assert m.profit_factor == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

class TestDrawdown:
    def test_max_drawdown_non_positive(self):
        m = compute_metrics(_mixed())
        assert m.max_drawdown <= 0

    def test_max_drawdown_zero_for_all_winners(self):
        m = compute_metrics(_all_winners())
        # Aucune perte → pas de drawdown (equity toujours croissante)
        assert m.max_drawdown <= 0

    def test_max_drawdown_from_equity_curve(self):
        """Le drawdown calculé depuis l'equity curve doit être cohérent."""
        equity = pd.Series([10_000, 10_100, 10_050, 9_800, 9_900, 10_200])
        # pic à 10_100 puis plancher à 9_800 → dd = -300
        m = compute_metrics(_all_winners(1), equity_curve=equity)
        assert m.max_drawdown <= 0


# ---------------------------------------------------------------------------
# Sharpe / Sortino
# ---------------------------------------------------------------------------

class TestRatios:
    def test_sharpe_positive_for_profitable(self):
        m = compute_metrics(_all_winners(20))
        # Toujours gagnant → Sharpe très élevé
        assert m.sharpe_ratio > 0

    def test_sortino_positive_for_profitable(self):
        m = compute_metrics(_all_winners(20))
        assert m.sortino_ratio > 0

    def test_sharpe_negative_for_losing(self):
        m = compute_metrics(_all_losers(20))
        assert m.sharpe_ratio < 0

    def test_sortino_inf_for_no_downside(self):
        """Sans pertes, le Sortino devrait être infini ou très élevé."""
        m = compute_metrics(_all_winners(20))
        assert m.sortino_ratio == float("inf") or m.sortino_ratio > 10

    def test_single_trade_returns_zero_ratios(self):
        """Pas assez de données pour calculer un écart-type."""
        m = compute_metrics([_make_trade(100.0)])
        assert m.sharpe_ratio == 0.0


# ---------------------------------------------------------------------------
# MetricsResult __str__
# ---------------------------------------------------------------------------

class TestStr:
    def test_str_contains_win_rate(self):
        m = compute_metrics(_mixed())
        assert "Win Rate" in str(m)

    def test_str_contains_sharpe(self):
        m = compute_metrics(_mixed())
        assert "Sharpe" in str(m)
