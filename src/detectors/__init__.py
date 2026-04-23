"""
Detectors package — public pipeline API.

Typical usage (full pipeline in order):

    from detectors import run_pipeline

    enriched_df, artifacts = run_pipeline(ohlcv_df)

Or module by module:

    from detectors.sessions   import detect_sessions
    from detectors.structure  import detect_structure
    from detectors.liquidity  import detect_liquidity
    from detectors.fvg        import detect_fvg
    from detectors.orderblock import detect_ob
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from detectors.sessions   import detect_sessions
from detectors.structure  import detect_structure
from detectors.fvg        import detect_fvg, FVG
from detectors.liquidity  import detect_liquidity, LiquidityPool
from detectors.orderblock import detect_ob, OrderBlock


@dataclass
class PipelineArtifacts:
    """All structured objects produced by the detection pipeline."""
    fvgs:   list[FVG]
    pools:  list[LiquidityPool]
    obs:    list[OrderBlock]


def run_pipeline(
    df: pd.DataFrame,
    structure_lookback: int = 5,
    fvg_body_ratio: float = 0.5,
    liquidity_range_pct: float = 0.001,
    ob_lookback: int = 10,
    filter_asian_fvg: bool = True,
) -> tuple[pd.DataFrame, PipelineArtifacts]:
    """
    Run the full ICT/SMC detection pipeline on an OHLCV DataFrame.

    Pipeline order (each stage consumes columns from the previous):
        1. sessions   -> session, in_kill_zone, ar_high, ar_low, amd_phase
        2. structure  -> swing_high, swing_low, trend, bos_*, choch_*, last_sh/sl
        3. fvg        -> fvg_bull, fvg_bear  (+ FVG objects)
        4. liquidity  -> bsl, ssl, eqh, eql, sweep_bull, sweep_bear  (+ Pool objects)
        5. orderblock -> ob_bull, ob_bear, breaker_bull, breaker_bear (+ OB objects)

    Args:
        df:                   OHLCV DataFrame (canonical format from fetcher.py).
        structure_lookback:   Swing point confirmation window (bars each side).
        fvg_body_ratio:       Minimum body/range for FVG middle candle.
        liquidity_range_pct:  Price tolerance to cluster equal highs/lows.
        ob_lookback:          Bars to search back for the OB candle.
        filter_asian_fvg:     Skip FVGs formed during the Asian session.

    Returns:
        (enriched DataFrame, PipelineArtifacts)
    """
    df = detect_sessions(df)
    df = detect_structure(df, lookback=structure_lookback)
    df, fvgs  = detect_fvg(df, min_body_ratio=fvg_body_ratio, filter_asian=filter_asian_fvg)
    df, pools = detect_liquidity(df, range_pct=liquidity_range_pct)
    df, obs   = detect_ob(df, fvgs=fvgs, lookback=ob_lookback)

    return df, PipelineArtifacts(fvgs=fvgs, pools=pools, obs=obs)


__all__ = [
    "run_pipeline",
    "PipelineArtifacts",
    "detect_sessions",
    "detect_structure",
    "detect_fvg",
    "detect_liquidity",
    "detect_ob",
    "FVG",
    "LiquidityPool",
    "OrderBlock",
]
