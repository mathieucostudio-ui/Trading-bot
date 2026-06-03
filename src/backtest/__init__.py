"""
Package backtest — moteur de simulation, métriques, walk-forward.

    from backtest.engine     import run_backtest, BacktestConfig, Trade, BacktestResult
    from backtest.metrics    import compute_metrics, MetricsResult
    from backtest.walkforward import walk_forward, WalkForwardResult
"""
from backtest.engine      import BacktestConfig, Trade, BacktestResult, run_backtest
from backtest.metrics     import MetricsResult, compute_metrics
from backtest.walkforward import WalkForwardResult, WalkForwardWindow, walk_forward

__all__ = [
    "BacktestConfig",
    "Trade",
    "BacktestResult",
    "run_backtest",
    "MetricsResult",
    "compute_metrics",
    "WalkForwardResult",
    "WalkForwardWindow",
    "walk_forward",
]
