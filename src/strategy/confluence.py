"""
ICT/SMC Confluence Scorer.

Scores each bar 0–5 based on how many of the five ICT entry factors align:

  1. Kill Zone      — bar falls inside London (02-05 EST) or NY (08-11 EST)
  2. Liquidity Sweep — recent sweep of BSL or SSL within the lookback window
  3. Displacement    — BOS or CHoCH within the lookback window (impulse move)
  4. CHoCH           — a Change of Character exists within the lookback window
                       (directional flip, higher conviction than BOS alone)
  5. OB / FVG        — current bar sits inside a live Order Block or FVG zone

The scorer is directional: long_score and short_score are computed separately.
A signal direction is only valid when its score reaches the minimum threshold.
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
class ConfluenceScore:
    """Per-bar confluence result."""
    bar_index: int
    timestamp: pd.Timestamp
    long_score: int    # 0–5
    short_score: int   # 0–5
    # Component flags (long perspective; short mirrors them with opposite cols)
    in_kill_zone: bool
    has_sweep: bool
    has_displacement: bool
    has_choch: bool
    has_ob_fvg: bool

    @property
    def max_score(self) -> int:
        return max(self.long_score, self.short_score)

    @property
    def direction(self) -> Optional[str]:
        """'long' | 'short' | None if scores equal or below threshold."""
        if self.long_score > self.short_score:
            return "long"
        if self.short_score > self.long_score:
            return "short"
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_confluence(
    df: pd.DataFrame,
    lookback: int = 5,
) -> list[ConfluenceScore]:
    """
    Score every bar in a fully-enriched pipeline DataFrame.

    The DataFrame must have columns produced by the full detection pipeline:
        in_kill_zone, sweep_bull, sweep_bear,
        bos_bull, bos_bear, choch_bull, choch_bear,
        ob_bull, ob_bear, fvg_bull, fvg_bear

    Args:
        df:       DataFrame from run_pipeline().
        lookback: How many bars back to search for sweep/displacement/CHoCH.

    Returns:
        List of ConfluenceScore objects, one per bar.
    """
    _require_columns(df)
    n = len(df)

    in_kz       = df["in_kill_zone"].values.astype(bool)
    sweep_bull  = df["sweep_bull"].values.astype(bool)
    sweep_bear  = df["sweep_bear"].values.astype(bool)
    bos_bull    = df["bos_bull"].values.astype(bool)
    bos_bear    = df["bos_bear"].values.astype(bool)
    choch_bull  = df["choch_bull"].values.astype(bool)
    choch_bear  = df["choch_bear"].values.astype(bool)
    ob_bull     = df["ob_bull"].values.astype(bool)
    ob_bear     = df["ob_bear"].values.astype(bool)
    fvg_bull    = df["fvg_bull"].values.astype(bool)
    fvg_bear    = df["fvg_bear"].values.astype(bool)

    scores: list[ConfluenceScore] = []

    for i in range(n):
        lb_start = max(0, i - lookback + 1)
        window   = slice(lb_start, i + 1)

        # Factor 1: Kill Zone (current bar only)
        kz = bool(in_kz[i])

        # Factor 2: Liquidity sweep anywhere in window
        bull_sweep_present = sweep_bull[window].any()
        bear_sweep_present = sweep_bear[window].any()

        # Factor 3: Displacement (BOS or CHoCH in window)
        bull_disp = (bos_bull[window] | choch_bull[window]).any()
        bear_disp = (bos_bear[window] | choch_bear[window]).any()

        # Factor 4: CHoCH specifically (trend flip)
        bull_choch = choch_bull[window].any()
        bear_choch = choch_bear[window].any()

        # Factor 5: OB or FVG at current bar
        bull_ob_fvg = bool(ob_bull[i] or fvg_bull[i])
        bear_ob_fvg = bool(ob_bear[i] or fvg_bear[i])

        long_score = sum([kz, bull_sweep_present, bull_disp, bull_choch, bull_ob_fvg])
        short_score = sum([kz, bear_sweep_present, bear_disp, bear_choch, bear_ob_fvg])

        scores.append(ConfluenceScore(
            bar_index=i,
            timestamp=df.index[i],
            long_score=int(long_score),
            short_score=int(short_score),
            in_kill_zone=kz,
            has_sweep=bull_sweep_present or bear_sweep_present,
            has_displacement=bull_disp or bear_disp,
            has_choch=bull_choch or bear_choch,
            has_ob_fvg=bull_ob_fvg or bear_ob_fvg,
        ))

    return scores


def add_confluence_columns(
    df: pd.DataFrame,
    lookback: int = 5,
) -> pd.DataFrame:
    """
    Convenience wrapper that attaches long_score / short_score columns to df.

    Returns a copy with two new integer columns: long_score, short_score.
    """
    scores = score_confluence(df, lookback=lookback)
    df = df.copy()
    df["long_score"]  = [s.long_score  for s in scores]
    df["short_score"] = [s.short_score for s in scores]
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame) -> None:
    required = (
        "in_kill_zone", "sweep_bull", "sweep_bear",
        "bos_bull", "bos_bear", "choch_bull", "choch_bear",
        "ob_bull", "ob_bear", "fvg_bull", "fvg_bear",
    )
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing columns for confluence scoring: {missing}. "
            "Run the full detection pipeline first (run_pipeline())."
        )
