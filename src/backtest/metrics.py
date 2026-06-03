"""
Métriques de performance pour les résultats de backtest.

Toutes les métriques sont calculées à partir d'une liste de Trade objects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class MetricsResult:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float             # 0.0 – 1.0
    avg_r: float                # moyenne des gains/pertes en multiples de R
    profit_factor: float        # gross_profit / gross_loss (inf si aucune perte)
    sharpe_ratio: float         # annualisé, basé sur les PnL des trades
    sortino_ratio: float        # comme Sharpe mais ne pénalise que la volatilité négative
    max_drawdown: float         # valeur négative ou 0 (en USD)
    max_drawdown_pct: float     # en % du pic d'equity
    total_pnl: float            # USD net
    total_return_pct: float     # % de l'equity initiale
    avg_trade_pnl: float        # USD par trade
    avg_winner_pnl: float       # USD des trades gagnants
    avg_loser_pnl: float        # USD des trades perdants (négatif)

    def __str__(self) -> str:
        lines = [
            f"Trades        : {self.total_trades} ({self.winning_trades}W / {self.losing_trades}L)",
            f"Win Rate      : {self.win_rate:.1%}",
            f"Avg R         : {self.avg_r:+.2f}R",
            f"Profit Factor : {self.profit_factor:.2f}",
            f"Sharpe        : {self.sharpe_ratio:.2f}",
            f"Sortino       : {self.sortino_ratio:.2f}",
            f"Max Drawdown  : {self.max_drawdown:+.2f} USD ({self.max_drawdown_pct:.1%})",
            f"Total PnL     : {self.total_pnl:+.2f} USD ({self.total_return_pct:+.1%})",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_metrics(
    trades: list,
    initial_balance: float = 10_000.0,
    equity_curve: Optional[pd.Series] = None,
    bars_per_year: int = 252 * 24 * 4,  # 15-min bars in a trading year
) -> MetricsResult:
    """
    Compute performance metrics from a list of Trade objects.

    Args:
        trades:          Liste de Trade (fermés et ouverts à fin de période).
        initial_balance: Capital de départ pour le calcul de return %.
        equity_curve:    Si fournie, utilisée pour le drawdown exact.
        bars_per_year:   Pour l'annualisation du Sharpe (défaut: 15 min × 24h × 252j).

    Returns:
        MetricsResult
    """
    closed = [t for t in trades if t.pnl is not None]

    if not closed:
        return _empty_metrics()

    pnls   = np.array([t.pnl   for t in closed], dtype=float)
    pnl_r  = np.array([t.pnl_r for t in closed], dtype=float)
    winners = pnls[pnls > 0]
    losers  = pnls[pnls <= 0]

    total_trades   = len(closed)
    winning_trades = int((pnls > 0).sum())
    losing_trades  = int((pnls <= 0).sum())
    win_rate       = winning_trades / total_trades

    avg_r = float(pnl_r.mean()) if len(pnl_r) > 0 else 0.0

    gross_profit = float(winners.sum()) if len(winners) > 0 else 0.0
    gross_loss   = float(abs(losers.sum())) if len(losers) > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    sharpe  = _sharpe(pnls, bars_per_year)
    sortino = _sortino(pnls, bars_per_year)

    total_pnl        = float(pnls.sum())
    total_return_pct = total_pnl / initial_balance
    avg_trade_pnl    = float(pnls.mean())
    avg_winner_pnl   = float(winners.mean()) if len(winners) > 0 else 0.0
    avg_loser_pnl    = float(losers.mean())  if len(losers)  > 0 else 0.0

    if equity_curve is not None and len(equity_curve) > 0:
        dd, dd_pct = _max_drawdown_from_equity(equity_curve)
    else:
        dd, dd_pct = _max_drawdown_from_pnls(pnls, initial_balance)

    return MetricsResult(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        avg_r=avg_r,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=dd,
        max_drawdown_pct=dd_pct,
        total_pnl=total_pnl,
        total_return_pct=total_return_pct,
        avg_trade_pnl=avg_trade_pnl,
        avg_winner_pnl=avg_winner_pnl,
        avg_loser_pnl=avg_loser_pnl,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sharpe(pnls: np.ndarray, bars_per_year: int) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = pnls.mean()
    std  = pnls.std(ddof=1)
    if std == 0:
        return 0.0
    trades_per_year = bars_per_year / max(1, len(pnls))
    return float((mean / std) * np.sqrt(trades_per_year))


def _sortino(pnls: np.ndarray, bars_per_year: int) -> float:
    if len(pnls) < 2:
        return 0.0
    mean          = pnls.mean()
    downside      = pnls[pnls < 0]
    downside_std  = downside.std(ddof=1) if len(downside) > 1 else (abs(downside[0]) if len(downside) == 1 else 0.0)
    if downside_std == 0:
        return float("inf") if mean > 0 else 0.0
    trades_per_year = bars_per_year / max(1, len(pnls))
    return float((mean / downside_std) * np.sqrt(trades_per_year))


def _max_drawdown_from_equity(equity: pd.Series) -> tuple[float, float]:
    vals  = equity.values.astype(float)
    peaks = np.maximum.accumulate(vals)
    dds   = vals - peaks
    max_dd = float(dds.min())
    # % relative to the peak at the worst point
    worst_idx = int(np.argmin(dds))
    peak_at_worst = float(peaks[worst_idx])
    max_dd_pct = max_dd / peak_at_worst if peak_at_worst > 0 else 0.0
    return max_dd, max_dd_pct


def _max_drawdown_from_pnls(pnls: np.ndarray, initial_balance: float) -> tuple[float, float]:
    equity = np.cumsum(np.concatenate([[initial_balance], pnls]))
    return _max_drawdown_from_equity(pd.Series(equity))


def _empty_metrics() -> MetricsResult:
    return MetricsResult(
        total_trades=0, winning_trades=0, losing_trades=0,
        win_rate=0.0, avg_r=0.0, profit_factor=0.0,
        sharpe_ratio=0.0, sortino_ratio=0.0,
        max_drawdown=0.0, max_drawdown_pct=0.0,
        total_pnl=0.0, total_return_pct=0.0,
        avg_trade_pnl=0.0, avg_winner_pnl=0.0, avg_loser_pnl=0.0,
    )
