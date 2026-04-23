"""
Fair Value Gap (FVG) detection and lifecycle tracking.

An FVG is a 3-candle imbalance where price moved so fast that the auction
process left an unfilled gap.  Institutions use these zones as future
entry / reaction areas.

Pattern (0-indexed, processing bar i as the LAST of three):
    Bullish FVG : low[i] > high[i-2]   →  gap zone = (high[i-2], low[i])
    Bearish FVG : high[i] < low[i-2]   →  gap zone = (high[i], low[i-2])

The middle candle (i-1) must be a strong momentum candle
(body / full_range >= min_body_ratio) to filter out noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class FVG:
    kind: str           # 'bull' | 'bear'
    top: float          # upper boundary of the gap zone
    bottom: float       # lower boundary of the gap zone
    bar_index: int      # index of the LAST candle of the 3-candle pattern
    timestamp: pd.Timestamp
    status: str = "active"           # 'active' | 'partial' | 'mitigated'
    mitigation_index: Optional[int] = None

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def size(self) -> float:
        return self.top - self.bottom


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_fvg(
    df: pd.DataFrame,
    min_body_ratio: float = 0.5,
    filter_asian: bool = True,
) -> tuple[pd.DataFrame, list[FVG]]:
    """
    Detect all Fair Value Gaps in an OHLCV DataFrame.

    Added columns:
        fvg_bull : bool — bar falls inside at least one active bullish FVG
        fvg_bear : bool — bar falls inside at least one active bearish FVG

    Args:
        df:             OHLCV DataFrame (canonical format). May optionally
                        contain a 'session' column from sessions.py.
        min_body_ratio: Minimum body/range ratio for the middle candle.
                        Filters noise candles (doji, spinning tops).
        filter_asian:   If True and 'session' column exists, discard FVGs
                        whose middle candle is in the Asian session (thin volume).

    Returns:
        (enriched_df, list_of_FVG_objects)
    """
    df = df.copy()
    fvgs = _find_fvgs(df, min_body_ratio, filter_asian)
    fvgs = _update_status(df, fvgs)
    df   = _tag_columns(df, fvgs)
    return df, fvgs


def get_active_fvgs(fvgs: list[FVG], kind: Optional[str] = None) -> list[FVG]:
    """Return FVGs that are not yet fully mitigated."""
    result = [f for f in fvgs if f.status != "mitigated"]
    if kind:
        result = [f for f in result if f.kind == kind]
    return result


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _find_fvgs(
    df: pd.DataFrame,
    min_body_ratio: float,
    filter_asian: bool,
) -> list[FVG]:
    highs  = df["High"].values
    lows   = df["Low"].values
    opens  = df["Open"].values
    closes = df["Close"].values
    n = len(df)

    has_session = "session" in df.columns
    sessions = df["session"].values if has_session else None

    fvgs: list[FVG] = []

    for i in range(2, n):
        mid = i - 1   # middle (momentum) candle

        # Quality filter on the middle candle
        body   = abs(closes[mid] - opens[mid])
        rng    = highs[mid] - lows[mid]
        if rng == 0 or body / rng < min_body_ratio:
            continue

        # Asian session filter
        if filter_asian and has_session and sessions[mid] == "asian":
            continue

        # --- Bullish FVG ---
        if lows[i] > highs[i - 2]:
            fvgs.append(FVG(
                kind="bull",
                top=lows[i],
                bottom=highs[i - 2],
                bar_index=i,
                timestamp=df.index[i],
            ))

        # --- Bearish FVG ---
        elif highs[i] < lows[i - 2]:
            fvgs.append(FVG(
                kind="bear",
                top=lows[i - 2],
                bottom=highs[i],
                bar_index=i,
                timestamp=df.index[i],
            ))

    return fvgs


# ---------------------------------------------------------------------------
# Lifecycle tracking
# ---------------------------------------------------------------------------

def _update_status(df: pd.DataFrame, fvgs: list[FVG]) -> list[FVG]:
    """
    For each FVG, scan future bars to determine if / when it was mitigated.

    - PARTIAL   : price enters the zone (high > bottom for bull, low < top for bear)
                  but the bar does NOT close through the far boundary.
    - MITIGATED : a bar closes beyond the zone's far boundary
                  (close < bottom for bull, close > top for bear).
    """
    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    n = len(df)

    for fvg in fvgs:
        start = fvg.bar_index + 1
        for j in range(start, n):
            if fvg.kind == "bull":
                entered = lows[j] <= fvg.top      # price dips into zone
                closed_through = closes[j] < fvg.bottom
            else:
                entered = highs[j] >= fvg.bottom  # price rises into zone
                closed_through = closes[j] > fvg.top

            if closed_through:
                fvg.status = "mitigated"
                fvg.mitigation_index = j
                break
            elif entered and fvg.status == "active":
                fvg.status = "partial"

    return fvgs


# ---------------------------------------------------------------------------
# DataFrame column tagging
# ---------------------------------------------------------------------------

def _tag_columns(df: pd.DataFrame, fvgs: list[FVG]) -> pd.DataFrame:
    """
    Add fvg_bull / fvg_bear boolean columns indicating whether each bar
    sits inside at least one non-mitigated FVG zone.
    """
    n = len(df)
    fvg_bull = np.zeros(n, dtype=bool)
    fvg_bear = np.zeros(n, dtype=bool)

    highs  = df["High"].values
    lows   = df["Low"].values

    for fvg in fvgs:
        if fvg.status == "mitigated":
            end = fvg.mitigation_index
        else:
            end = n

        for j in range(fvg.bar_index, end):
            if fvg.kind == "bull":
                # Bar overlaps the gap zone from below
                if lows[j] <= fvg.top and highs[j] >= fvg.bottom:
                    fvg_bull[j] = True
            else:
                if highs[j] >= fvg.bottom and lows[j] <= fvg.top:
                    fvg_bear[j] = True

    df["fvg_bull"] = fvg_bull
    df["fvg_bear"] = fvg_bear
    return df
