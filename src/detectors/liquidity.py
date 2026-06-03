"""
Liquidity pool detection and sweep identification.

Liquidity pools are price levels where retail stop-loss orders cluster.
Institutions engineer price to reach these levels (sweeping them), absorb
the resulting market orders, then reverse.

Types of pools detected:
  - Equal Highs (EQH)  : two or more swing highs within `range_pct` of each other
  - Equal Lows  (EQL)  : two or more swing lows  within `range_pct` of each other
  - Buy-Side Liquidity (BSL) : above prior swing highs → short-seller stops
  - Sell-Side Liquidity (SSL): below prior swing lows  → long-trader stops

Sweep confirmation: wick beyond the pool level + close back on the other side.

Requires: df must already contain 'swing_high' and 'swing_low' columns
          from detectors/structure.py.
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
class LiquidityPool:
    kind: str           # 'bsl' (buy-side) | 'ssl' (sell-side) | 'eqh' | 'eql'
    level: float        # price level of the pool
    bar_index: int      # bar where the pool was created (last swing)
    timestamp: pd.Timestamp
    swept: bool = False
    sweep_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_liquidity(
    df: pd.DataFrame,
    range_pct: float = 0.001,
) -> tuple[pd.DataFrame, list[LiquidityPool]]:
    """
    Detect all liquidity pools and sweeps.

    Added columns:
        bsl          : float | NaN — nearest buy-side liquidity above current bar
        ssl          : float | NaN — nearest sell-side liquidity below current bar
        eqh          : float | NaN — equal highs level at this bar (if confirmed)
        eql          : float | NaN — equal lows level at this bar (if confirmed)
        sweep_bull   : bool — sell-side liquidity was just swept (bullish signal)
        sweep_bear   : bool — buy-side liquidity was just swept (bearish signal)

    Args:
        df:        OHLCV DataFrame with 'swing_high' and 'swing_low' columns.
        range_pct: Maximum price distance (as fraction) to cluster swings as equal.

    Returns:
        (enriched_df, list_of_LiquidityPool_objects)
    """
    df = df.copy()
    _require_structure(df)

    pools = _build_pools(df, range_pct)
    pools = _detect_sweeps(df, pools)
    df    = _tag_columns(df, pools)
    return df, pools


def get_unswept_pools(pools: list[LiquidityPool], kind: Optional[str] = None) -> list[LiquidityPool]:
    """Return pools that have not yet been swept."""
    result = [p for p in pools if not p.swept]
    if kind:
        result = [p for p in result if p.kind == kind]
    return result


# ---------------------------------------------------------------------------
# Pool construction
# ---------------------------------------------------------------------------

def _require_structure(df: pd.DataFrame) -> None:
    for col in ("swing_high", "swing_low"):
        if col not in df.columns:
            raise ValueError(
                f"Column '{col}' not found. Run detect_structure() first."
            )


def _build_pools(df: pd.DataFrame, range_pct: float) -> list[LiquidityPool]:
    pools: list[LiquidityPool] = []

    sh_mask = ~df["swing_high"].isna()
    sl_mask = ~df["swing_low"].isna()

    sh_idx    = np.where(sh_mask)[0]
    sl_idx    = np.where(sl_mask)[0]
    sh_prices = df["swing_high"].values[sh_idx]
    sl_prices = df["swing_low"].values[sl_idx]

    # --- BSL: every swing high is a buy-side liquidity level ---
    for i, idx in enumerate(sh_idx):
        pools.append(LiquidityPool(
            kind="bsl",
            level=sh_prices[i],
            bar_index=int(idx),
            timestamp=df.index[idx],
        ))

    # --- SSL: every swing low is a sell-side liquidity level ---
    for i, idx in enumerate(sl_idx):
        pools.append(LiquidityPool(
            kind="ssl",
            level=sl_prices[i],
            bar_index=int(idx),
            timestamp=df.index[idx],
        ))

    # --- EQH: cluster nearby swing highs ---
    eqh_pools = _cluster_equal_levels(
        sh_idx, sh_prices, df, "eqh", range_pct
    )
    pools.extend(eqh_pools)

    # --- EQL: cluster nearby swing lows ---
    eql_pools = _cluster_equal_levels(
        sl_idx, sl_prices, df, "eql", range_pct
    )
    pools.extend(eql_pools)

    return pools


def _cluster_equal_levels(
    indices: np.ndarray,
    prices: np.ndarray,
    df: pd.DataFrame,
    kind: str,
    range_pct: float,
) -> list[LiquidityPool]:
    """
    Find clusters of swing points within `range_pct` of each other.
    Each cluster becomes one LiquidityPool at the average level.
    Requires at least 2 points to form a cluster.
    """
    pools: list[LiquidityPool] = []
    if len(prices) < 2:
        return pools

    used = np.zeros(len(prices), dtype=bool)

    for i in range(len(prices)):
        if used[i]:
            continue
        ref = prices[i]
        cluster_idx = [i]
        for j in range(i + 1, len(prices)):
            if used[j]:
                continue
            if abs(prices[j] - ref) / ref <= range_pct:
                cluster_idx.append(j)

        if len(cluster_idx) >= 2:
            avg_level = float(np.mean(prices[cluster_idx]))
            last_bar  = int(indices[cluster_idx[-1]])
            pools.append(LiquidityPool(
                kind=kind,
                level=avg_level,
                bar_index=last_bar,
                timestamp=df.index[last_bar],
            ))
            for ci in cluster_idx:
                used[ci] = True

    return pools


# ---------------------------------------------------------------------------
# Sweep detection
# ---------------------------------------------------------------------------

def _detect_sweeps(df: pd.DataFrame, pools: list[LiquidityPool]) -> list[LiquidityPool]:
    """
    Mark each pool as swept when price wicks through it and closes back.

    BSL sweep (bearish): wick above level + close below level → institutions sold into buystops
    SSL sweep (bullish): wick below level + close above level → institutions bought into sellstops
    """
    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    n = len(df)

    for pool in pools:
        start = pool.bar_index + 1
        for j in range(start, n):
            if pool.kind in ("bsl", "eqh"):
                # Sweep of buy-side: wick above, close below
                if highs[j] > pool.level and closes[j] < pool.level:
                    pool.swept = True
                    pool.sweep_index = j
                    break
            else:
                # Sweep of sell-side: wick below, close above
                if lows[j] < pool.level and closes[j] > pool.level:
                    pool.swept = True
                    pool.sweep_index = j
                    break

    return pools


# ---------------------------------------------------------------------------
# DataFrame column tagging
# ---------------------------------------------------------------------------

def _tag_columns(df: pd.DataFrame, pools: list[LiquidityPool]) -> pd.DataFrame:
    n = len(df)
    closes = df["Close"].values

    bsl_col      = np.full(n, np.nan)
    ssl_col      = np.full(n, np.nan)
    eqh_col      = np.full(n, np.nan)
    eql_col      = np.full(n, np.nan)
    sweep_bull   = np.zeros(n, dtype=bool)
    sweep_bear   = np.zeros(n, dtype=bool)

    # For each bar, find nearest BSL above and SSL below
    for i in range(n):
        c = closes[i]

        above = [p.level for p in pools if p.kind in ("bsl", "eqh")
                 and p.bar_index < i and p.level > c and not p.swept]
        below = [p.level for p in pools if p.kind in ("ssl", "eql")
                 and p.bar_index < i and p.level < c and not p.swept]

        if above:
            bsl_col[i] = min(above)   # nearest BSL above
        if below:
            ssl_col[i] = max(below)   # nearest SSL below

    # Mark equal high/low confirmation bars
    for pool in pools:
        if pool.kind == "eqh":
            eqh_col[pool.bar_index] = pool.level
        elif pool.kind == "eql":
            eql_col[pool.bar_index] = pool.level

    # Mark sweep events
    for pool in pools:
        if pool.swept and pool.sweep_index is not None:
            if pool.kind in ("ssl", "eql"):
                sweep_bull[pool.sweep_index] = True   # SSL swept → bullish reversal
            else:
                sweep_bear[pool.sweep_index] = True   # BSL swept → bearish reversal

    df["bsl"]        = bsl_col
    df["ssl"]        = ssl_col
    df["eqh"]        = eqh_col
    df["eql"]        = eql_col
    df["sweep_bull"] = sweep_bull
    df["sweep_bear"] = sweep_bear
    return df
