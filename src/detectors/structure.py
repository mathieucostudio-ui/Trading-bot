"""
Market structure detection: swing points, trend, BOS, CHoCH.

Detection is close-based only (no wick qualifies as a structural break).

Right-side lag: a swing at bar i is only visually confirmed once bars
i+1 … i+lookback have closed. The break detection (BOS/CHoCH) happens
on the bar whose close crosses the swing level, so there is no look-ahead
bias in the break signals themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StructureEvent:
    """A single BOS or CHoCH event."""
    kind: str           # 'BOS_BULL' | 'BOS_BEAR' | 'CHOCH_BULL' | 'CHOCH_BEAR'
    level: float        # the structural level that was broken
    bar_index: int
    timestamp: pd.Timestamp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_structure(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Full market structure pipeline on a single OHLCV DataFrame.

    Added columns:
        swing_high  : float | NaN — confirmed swing high price at this bar
        swing_low   : float | NaN — confirmed swing low price at this bar
        trend       : int  — 1 (bull) | -1 (bear) | 0 (undefined)
        bos_bull    : bool — bullish Break of Structure (close > last swing high, in bull trend)
        bos_bear    : bool — bearish Break of Structure (close < last swing low, in bear trend)
        choch_bull  : bool — bullish Change of Character (close > last swing high, in bear trend)
        choch_bear  : bool — bearish Change of Character (close < last swing low, in bull trend)
        last_sh     : float — last confirmed swing high level (state-carried forward)
        last_sl     : float — last confirmed swing low level (state-carried forward)

    Args:
        df:       OHLCV DataFrame with UTC DatetimeIndex (canonical format from fetcher.py).
        lookback: Bars required on each side to confirm a swing point.

    Returns:
        Copy of df with structure columns added.
    """
    df = df.copy()
    df = _detect_swing_points(df, lookback)
    df = _classify_bos_choch(df)
    return df


def get_structure_events(df: pd.DataFrame) -> list[StructureEvent]:
    """Return all BOS / CHoCH events from a structure-annotated DataFrame."""
    events: list[StructureEvent] = []
    for col, kind in (
        ("bos_bull", "BOS_BULL"),
        ("bos_bear", "BOS_BEAR"),
        ("choch_bull", "CHOCH_BULL"),
        ("choch_bear", "CHOCH_BEAR"),
    ):
        if col not in df.columns:
            continue
        hits = df[df[col]]
        for pos, row in hits.iterrows():
            events.append(StructureEvent(
                kind=kind,
                level=row["last_sh"] if "BULL" in kind else row["last_sl"],
                bar_index=df.index.get_loc(pos),
                timestamp=pos,
            ))
    events.sort(key=lambda e: e.bar_index)
    return events


# ---------------------------------------------------------------------------
# Swing point detection
# ---------------------------------------------------------------------------

def _detect_swing_points(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    sh = np.full(n, np.nan)
    sl = np.full(n, np.nan)

    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback: i + lookback + 1]
        # Strict maximum: bar i must be strictly higher than every other bar in window
        if highs[i] > np.max(np.concatenate([window_h[:lookback], window_h[lookback + 1:]])):
            sh[i] = highs[i]

        window_l = lows[i - lookback: i + lookback + 1]
        if lows[i] < np.min(np.concatenate([window_l[:lookback], window_l[lookback + 1:]])):
            sl[i] = lows[i]

    df["swing_high"] = sh
    df["swing_low"] = sl
    return df


# ---------------------------------------------------------------------------
# BOS / CHoCH classification (sequential state machine)
# ---------------------------------------------------------------------------

def _classify_bos_choch(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    closes = df["Close"].values
    sh_vals = df["swing_high"].values
    sl_vals = df["swing_low"].values

    bos_bull  = np.zeros(n, dtype=bool)
    bos_bear  = np.zeros(n, dtype=bool)
    choch_bull = np.zeros(n, dtype=bool)
    choch_bear = np.zeros(n, dtype=bool)
    trend_arr  = np.zeros(n, dtype=int)
    last_sh_arr = np.full(n, np.nan)
    last_sl_arr = np.full(n, np.nan)

    # Mutable state
    _trend: int = 0
    _sh: Optional[float] = None   # active structural high
    _sl: Optional[float] = None   # active structural low
    _sh_broken: bool = False       # prevent re-triggering on the same level
    _sl_broken: bool = False

    for i in range(n):
        c = closes[i]

        # --- 1. Detect break BEFORE updating swing levels (avoids same-bar conflict) ---
        if _sh is not None and not _sh_broken and c > _sh:
            _sh_broken = True
            if _trend == 1:
                bos_bull[i] = True
            else:
                choch_bull[i] = True
            _trend = 1

        elif _sl is not None and not _sl_broken and c < _sl:
            _sl_broken = True
            if _trend == -1:
                bos_bear[i] = True
            else:
                choch_bear[i] = True
            _trend = -1

        # --- 2. Update structural levels from confirmed swings at this bar ---
        if not np.isnan(sh_vals[i]):
            _sh = sh_vals[i]
            _sh_broken = False   # fresh level, reset break flag

        if not np.isnan(sl_vals[i]):
            _sl = sl_vals[i]
            _sl_broken = False

        trend_arr[i]  = _trend
        last_sh_arr[i] = _sh if _sh is not None else np.nan
        last_sl_arr[i] = _sl if _sl is not None else np.nan

    df["trend"]      = trend_arr
    df["bos_bull"]   = bos_bull
    df["bos_bear"]   = bos_bear
    df["choch_bull"] = choch_bull
    df["choch_bear"] = choch_bear
    df["last_sh"]    = last_sh_arr
    df["last_sl"]    = last_sl_arr
    return df
