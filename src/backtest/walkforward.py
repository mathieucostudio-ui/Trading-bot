"""
Walk-forward validation: fenêtres glissantes IS/OOS.

Principe :
  - IS (In-Sample)  : fenêtre d'entraînement, ex. 6 mois
  - OOS (Out-of-Sample) : fenêtre de test immédiatement après IS, ex. 2 mois
  - La fenêtre glisse de `oos_months` à chaque itération
  - Résultat : comparaison IS vs OOS pour détecter l'overfitting

Le ratio OOS/IS > 0.5 est un signe d'un edge robuste.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from backtest.engine import BacktestConfig, BacktestResult, Trade, run_backtest
from backtest.metrics import MetricsResult, compute_metrics


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardWindow:
    window_id: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    is_result: BacktestResult
    oos_result: BacktestResult
    is_metrics: MetricsResult
    oos_metrics: MetricsResult

    @property
    def robustness_ratio(self) -> float:
        """OOS win_rate / IS win_rate. > 0.5 = edge robuste."""
        if self.is_metrics.win_rate == 0:
            return 0.0
        return self.oos_metrics.win_rate / self.is_metrics.win_rate


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    config: BacktestConfig
    is_months: int
    oos_months: int

    @property
    def avg_oos_win_rate(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.oos_metrics.win_rate for w in self.windows) / len(self.windows)

    @property
    def avg_oos_sharpe(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.oos_metrics.sharpe_ratio for w in self.windows) / len(self.windows)

    @property
    def avg_robustness_ratio(self) -> float:
        if not self.windows:
            return 0.0
        return sum(w.robustness_ratio for w in self.windows) / len(self.windows)

    def summary(self) -> str:
        lines = [
            f"Walk-Forward: {len(self.windows)} fenêtres "
            f"(IS={self.is_months}m / OOS={self.oos_months}m)",
            f"  Avg OOS Win Rate  : {self.avg_oos_win_rate:.1%}",
            f"  Avg OOS Sharpe    : {self.avg_oos_sharpe:.2f}",
            f"  Avg Robustness    : {self.avg_robustness_ratio:.2f} "
            f"({'OK' if self.avg_robustness_ratio >= 0.5 else 'FAIBLE'})",
        ]
        for w in self.windows:
            lines.append(
                f"  [{w.window_id}] IS {w.is_start.date()}→{w.is_end.date()} "
                f"OOS {w.oos_start.date()}→{w.oos_end.date()} | "
                f"OOS trades={w.oos_metrics.total_trades} "
                f"WR={w.oos_metrics.win_rate:.1%} "
                f"R={w.oos_metrics.avg_r:+.2f}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def walk_forward(
    df: pd.DataFrame,
    is_months: int = 6,
    oos_months: int = 2,
    config: Optional[BacktestConfig] = None,
) -> WalkForwardResult:
    """
    Run a rolling walk-forward validation on a full historical DataFrame.

    Args:
        df:         Full OHLCV DataFrame (canonical format, UTC index).
        is_months:  In-sample window length in months.
        oos_months: Out-of-sample window length in months.
        config:     BacktestConfig to use for all windows.

    Returns:
        WalkForwardResult aggregating all windows.
    """
    if config is None:
        config = BacktestConfig()

    windows = _build_windows(df, is_months, oos_months)

    results: list[WalkForwardWindow] = []

    for wid, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
        is_df  = df.loc[is_start:is_end]
        oos_df = df.loc[oos_start:oos_end]

        if len(is_df) < 50 or len(oos_df) < 10:
            continue  # Not enough data for this window

        is_result  = run_backtest(is_df,  config)
        oos_result = run_backtest(oos_df, config)

        is_metrics  = compute_metrics(
            is_result.trades,
            initial_balance=config.initial_balance,
            equity_curve=is_result.equity_curve,
        )
        oos_metrics = compute_metrics(
            oos_result.trades,
            initial_balance=config.initial_balance,
            equity_curve=oos_result.equity_curve,
        )

        results.append(WalkForwardWindow(
            window_id=wid,
            is_start=is_start,
            is_end=is_end,
            oos_start=oos_start,
            oos_end=oos_end,
            is_result=is_result,
            oos_result=oos_result,
            is_metrics=is_metrics,
            oos_metrics=oos_metrics,
        ))

    return WalkForwardResult(
        windows=results,
        config=config,
        is_months=is_months,
        oos_months=oos_months,
    )


# ---------------------------------------------------------------------------
# Window builder
# ---------------------------------------------------------------------------

def _build_windows(
    df: pd.DataFrame,
    is_months: int,
    oos_months: int,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """
    Build non-overlapping IS/OOS window tuples that cover the full df range.
    """
    start = df.index[0]
    end   = df.index[-1]

    windows = []
    cursor  = start

    while True:
        is_start  = cursor
        is_end    = is_start  + pd.DateOffset(months=is_months)  - pd.Timedelta(seconds=1)
        oos_start = is_start  + pd.DateOffset(months=is_months)
        oos_end   = oos_start + pd.DateOffset(months=oos_months) - pd.Timedelta(seconds=1)

        if oos_end > end:
            break

        windows.append((is_start, is_end, oos_start, oos_end))
        cursor = oos_start  # slide by OOS length

    return windows
