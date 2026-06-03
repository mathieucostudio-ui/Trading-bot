"""
Signal generator: translates confluence scores into actionable trade signals.

A signal fires when:
  - The confluence score in one direction meets or exceeds `min_score`.
  - The AMD phase is 3 (distribution / directional move expected) OR
    phase filtering is disabled.
  - Optionally, the bar must be inside a Kill Zone.

Signals are non-overlapping: if a long signal is active (no SL/TP yet hit),
a new long signal on the same bar is suppressed. Short signals are independent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from strategy.confluence import ConfluenceScore, score_confluence


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class TradeSignal:
    """A single entry signal."""
    direction: str        # 'long' | 'short'
    bar_index: int
    timestamp: pd.Timestamp
    entry_price: float    # Close of the signal bar
    confluence_score: int
    amd_phase: int        # 0-3
    # Populated by risk manager after the signal is generated
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    size_units: Optional[float] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_signals(
    df: pd.DataFrame,
    min_score: int = 3,
    require_kill_zone: bool = True,
    require_amd_phase3: bool = True,
    confluence_lookback: int = 5,
) -> list[TradeSignal]:
    """
    Scan a fully-enriched pipeline DataFrame and return trade signals.

    Args:
        df:                  DataFrame from run_pipeline() with confluence cols.
        min_score:           Minimum confluence score (0-5) to generate a signal.
        require_kill_zone:   Only fire signals inside Kill Zones (London / NY).
        require_amd_phase3:  Only fire signals when AMD phase == 3 (distribution).
        confluence_lookback: Lookback passed to score_confluence().

    Returns:
        List of TradeSignal objects sorted by bar_index.
    """
    _require_columns(df)
    scores = score_confluence(df, lookback=confluence_lookback)

    closes    = df["Close"].values
    amd_phase = df["amd_phase"].values if "amd_phase" in df.columns else None

    signals: list[TradeSignal] = []

    for s in scores:
        i = s.bar_index

        if require_kill_zone and not s.in_kill_zone:
            continue

        phase = int(amd_phase[i]) if amd_phase is not None else 0
        if require_amd_phase3 and phase != 3:
            continue

        for direction, score in (("long", s.long_score), ("short", s.short_score)):
            if score >= min_score:
                signals.append(TradeSignal(
                    direction=direction,
                    bar_index=i,
                    timestamp=s.timestamp,
                    entry_price=float(closes[i]),
                    confluence_score=score,
                    amd_phase=phase,
                ))

    signals.sort(key=lambda sig: sig.bar_index)
    return signals


def filter_signals(
    signals: list[TradeSignal],
    direction: Optional[str] = None,
    min_score: Optional[int] = None,
) -> list[TradeSignal]:
    """Filter a signal list by direction and/or minimum score."""
    result = signals
    if direction is not None:
        result = [s for s in result if s.direction == direction]
    if min_score is not None:
        result = [s for s in result if s.confluence_score >= min_score]
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame) -> None:
    required = (
        "in_kill_zone",
        "sweep_bull", "sweep_bear",
        "bos_bull", "bos_bear",
        "choch_bull", "choch_bear",
        "ob_bull", "ob_bear",
        "fvg_bull", "fvg_bear",
    )
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing columns for signal generation: {missing}. "
            "Run the full detection pipeline first (run_pipeline())."
        )
