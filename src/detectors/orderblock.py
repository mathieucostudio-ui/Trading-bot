"""
Order Block (OB) and Breaker Block detection.

An Order Block is the LAST opposing candle immediately before an institutional
displacement move that causes a Break of Structure (BOS).

Bullish OB : last bearish candle before a bullish BOS displacement
Bearish OB : last bullish candle before a bearish BOS displacement

Validity requires:
  1. The opposing candle exists (bearish for bull OB, bullish for bear OB)
  2. The displacement following it creates a BOS (from structure.py)
  3. A Fair Value Gap exists within the displacement (from fvg.py)

Mitigation: when price closes through the entire OB zone, it is spent.
Breaker Blocks: a mitigated OB whose opposing swing was also swept — it
  flips polarity and becomes a zone of the opposite direction.

Requires df to have structure columns from detect_structure()
and the fvgs list from detect_fvg().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from detectors.fvg import FVG


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class OrderBlock:
    kind: str           # 'bull' | 'bear'
    top: float
    bottom: float
    bar_index: int      # index of the OB candle itself
    timestamp: pd.Timestamp
    bos_index: int      # index of the BOS bar that validated this OB
    has_fvg: bool = False
    mitigated: bool = False
    mitigation_index: Optional[int] = None
    is_breaker: bool = False    # True if this OB has flipped polarity

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def size(self) -> float:
        return self.top - self.bottom


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_ob(
    df: pd.DataFrame,
    fvgs: list[FVG],
    lookback: int = 10,
) -> tuple[pd.DataFrame, list[OrderBlock]]:
    """
    Detect Order Blocks and Breaker Blocks.

    Added columns:
        ob_bull    : bool — bar sits inside a non-mitigated bullish OB zone
        ob_bear    : bool — bar sits inside a non-mitigated bearish OB zone
        breaker_bull : bool — bar sits inside a bullish Breaker Block zone
        breaker_bear : bool — bar sits inside a bearish Breaker Block zone

    Args:
        df:       OHLCV DataFrame with structure columns (bos_bull, bos_bear,
                  swing_high, swing_low) from detect_structure().
        fvgs:     List of FVG objects from detect_fvg().
        lookback: How many bars back to search for the opposing candle
                  relative to the BOS bar.

    Returns:
        (enriched_df, list_of_OrderBlock_objects)
    """
    _require_structure(df)
    df = df.copy()

    obs   = _find_obs(df, fvgs, lookback)
    obs   = _update_mitigation(df, obs)
    obs   = _detect_breakers(df, obs)
    df    = _tag_columns(df, obs)
    return df, obs


def get_valid_obs(
    obs: list[OrderBlock],
    kind: Optional[str] = None,
    require_fvg: bool = True,
) -> list[OrderBlock]:
    """Return non-mitigated Order Blocks, optionally filtered."""
    result = [o for o in obs if not o.mitigated and not o.is_breaker]
    if kind:
        result = [o for o in result if o.kind == kind]
    if require_fvg:
        result = [o for o in result if o.has_fvg]
    return result


def get_breaker_blocks(
    obs: list[OrderBlock],
    kind: Optional[str] = None,
) -> list[OrderBlock]:
    """Return Breaker Blocks (mitigated OBs that have flipped polarity)."""
    result = [o for o in obs if o.is_breaker]
    if kind:
        result = [o for o in result if o.kind == kind]
    return result


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _require_structure(df: pd.DataFrame) -> None:
    for col in ("bos_bull", "bos_bear", "choch_bull", "choch_bear", "swing_high", "swing_low"):
        if col not in df.columns:
            raise ValueError(
                f"Column '{col}' missing. Run detect_structure() before detect_ob()."
            )


def _find_obs(
    df: pd.DataFrame,
    fvgs: list[FVG],
    lookback: int,
) -> list[OrderBlock]:
    opens    = df["Open"].values
    closes   = df["Close"].values
    highs    = df["High"].values
    lows     = df["Low"].values
    bos_bull   = df["bos_bull"].values
    bos_bear   = df["bos_bear"].values
    choch_bull = df["choch_bull"].values
    choch_bear = df["choch_bear"].values
    n = len(df)

    # Pre-build set of bar indices that have a FVG anywhere in a range
    fvg_indices = {fvg.bar_index for fvg in fvgs}

    obs: list[OrderBlock] = []

    for i in range(2, n):

        # --- Bullish OB: last bearish candle before bullish displacement ---
        # A structural break (BOS or CHoCH) in the bullish direction validates the OB.
        if bos_bull[i] or choch_bull[i]:
            ob_bar = _find_last_opposing(
                i, lookback, closes, opens,
                target_bearish=True,   # we want a bearish candle
            )
            if ob_bar is not None:
                has_fvg = any(ob_bar < fi <= i for fi in fvg_indices)
                obs.append(OrderBlock(
                    kind="bull",
                    top=highs[ob_bar],
                    bottom=lows[ob_bar],
                    bar_index=ob_bar,
                    timestamp=df.index[ob_bar],
                    bos_index=i,
                    has_fvg=has_fvg,
                ))

        # --- Bearish OB: last bullish candle before bearish displacement ---
        if bos_bear[i] or choch_bear[i]:
            ob_bar = _find_last_opposing(
                i, lookback, closes, opens,
                target_bearish=False,  # we want a bullish candle
            )
            if ob_bar is not None:
                has_fvg = any(ob_bar < fi <= i for fi in fvg_indices)
                obs.append(OrderBlock(
                    kind="bear",
                    top=highs[ob_bar],
                    bottom=lows[ob_bar],
                    bar_index=ob_bar,
                    timestamp=df.index[ob_bar],
                    bos_index=i,
                    has_fvg=has_fvg,
                ))

    return obs


def _find_last_opposing(
    bos_bar: int,
    lookback: int,
    closes: np.ndarray,
    opens: np.ndarray,
    target_bearish: bool,
) -> Optional[int]:
    """
    Search backwards from bos_bar for the last candle of the target direction.
    Returns the bar index, or None if not found within lookback.
    """
    start = max(0, bos_bar - lookback)
    for j in range(bos_bar - 1, start - 1, -1):
        is_bearish = closes[j] < opens[j]
        if target_bearish and is_bearish:
            return j
        if not target_bearish and not is_bearish:
            return j
    return None


# ---------------------------------------------------------------------------
# Mitigation
# ---------------------------------------------------------------------------

def _update_mitigation(df: pd.DataFrame, obs: list[OrderBlock]) -> list[OrderBlock]:
    """
    An OB is mitigated when price closes THROUGH its entire zone:
      - Bullish OB: close < bottom
      - Bearish OB: close > top
    """
    closes = df["Close"].values
    n = len(df)

    for ob in obs:
        for j in range(ob.bar_index + 1, n):
            if ob.kind == "bull" and closes[j] < ob.bottom:
                ob.mitigated = True
                ob.mitigation_index = j
                break
            elif ob.kind == "bear" and closes[j] > ob.top:
                ob.mitigated = True
                ob.mitigation_index = j
                break

    return obs


# ---------------------------------------------------------------------------
# Breaker Blocks
# ---------------------------------------------------------------------------

def _detect_breakers(df: pd.DataFrame, obs: list[OrderBlock]) -> list[OrderBlock]:
    """
    A mitigated OB whose price level was also associated with a liquidity sweep
    becomes a Breaker Block (polarity flip).

    Simplified rule: any mitigated OB where the mitigation bar shows a strong
    close in the direction of the break (body > 50 % of range) is a Breaker.
    The zone retains its coordinates but the kind flips.
    """
    opens  = df["Open"].values
    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values

    for ob in obs:
        if not ob.mitigated or ob.mitigation_index is None:
            continue
        j = ob.mitigation_index
        body = abs(closes[j] - opens[j])
        rng  = highs[j] - lows[j]
        if rng > 0 and body / rng > 0.5:
            ob.is_breaker = True
            # Flip kind: a former bullish OB that failed becomes bearish Breaker
            ob.kind = "bear" if ob.kind == "bull" else "bull"

    return obs


# ---------------------------------------------------------------------------
# DataFrame column tagging
# ---------------------------------------------------------------------------

def _tag_columns(df: pd.DataFrame, obs: list[OrderBlock]) -> pd.DataFrame:
    n = len(df)
    ob_bull      = np.zeros(n, dtype=bool)
    ob_bear      = np.zeros(n, dtype=bool)
    breaker_bull = np.zeros(n, dtype=bool)
    breaker_bear = np.zeros(n, dtype=bool)

    highs  = df["High"].values
    lows   = df["Low"].values

    for ob in obs:
        end = ob.mitigation_index if ob.mitigated and ob.mitigation_index else n
        for j in range(ob.bar_index, end):
            in_zone = lows[j] <= ob.top and highs[j] >= ob.bottom
            if not in_zone:
                continue
            if ob.is_breaker:
                if ob.kind == "bull":
                    breaker_bull[j] = True
                else:
                    breaker_bear[j] = True
            else:
                if ob.kind == "bull":
                    ob_bull[j] = True
                else:
                    ob_bear[j] = True

    df["ob_bull"]      = ob_bull
    df["ob_bear"]      = ob_bear
    df["breaker_bull"] = breaker_bull
    df["breaker_bear"] = breaker_bear
    return df
