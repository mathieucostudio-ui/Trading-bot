"""
Strategy package — confluence scoring and signal generation.

    from strategy.confluence import score_confluence, add_confluence_columns
    from strategy.signal     import generate_signals, filter_signals, TradeSignal
"""
from strategy.confluence import ConfluenceScore, score_confluence, add_confluence_columns
from strategy.signal     import TradeSignal, generate_signals, filter_signals

__all__ = [
    "ConfluenceScore",
    "score_confluence",
    "add_confluence_columns",
    "TradeSignal",
    "generate_signals",
    "filter_signals",
]
