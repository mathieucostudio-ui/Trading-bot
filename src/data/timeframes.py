"""
Multi-timeframe resampling.

Takes a base LTF DataFrame and produces HTF views by resampling.
This avoids multiple API calls: fetch once at the finest grain (15m),
derive 1h and 4h from it.

Resample rules follow OHLCV conventions:
  Open  → first bar of the period
  High  → max of the period
  Low   → min of the period
  Close → last bar of the period
  Volume → sum of the period
"""

from __future__ import annotations

import pandas as pd

# Maps human-readable TF strings to pandas offset aliases
_TF_TO_PANDAS_OFFSET: dict[str, str] = {
    "1m":  "1min",
    "2m":  "2min",
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "1h":  "1h",
    "60m": "1h",
    "90m": "90min",
    "4h":  "4h",
    "1d":  "1D",
    "1wk": "1W",
}

# Resample aggregation rules
_OHLCV_AGG = {
    "Open":   "first",
    "High":   "max",
    "Low":    "min",
    "Close":  "last",
    "Volume": "sum",
}


def resample(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """
    Resample a OHLCV DataFrame to a higher timeframe.

    The input DataFrame must have a UTC-aware DatetimeIndex and columns
    [Open, High, Low, Close, Volume] — the canonical format produced by fetcher.py.

    Args:
        df:        Source DataFrame (any timeframe, must be <= target_tf granularity).
        target_tf: Target timeframe string, e.g. "1h", "4h", "1d".

    Returns:
        Resampled DataFrame with the same column schema, UTC index, no NaN rows.

    Raises:
        ValueError: unknown timeframe string or input DataFrame is malformed.
    """
    if target_tf not in _TF_TO_PANDAS_OFFSET:
        raise ValueError(
            f"Unknown timeframe '{target_tf}'. "
            f"Supported: {list(_TF_TO_PANDAS_OFFSET)}"
        )

    offset = _TF_TO_PANDAS_OFFSET[target_tf]

    resampled = (
        df.resample(offset, label="left", closed="left")
        .agg(_OHLCV_AGG)
        .dropna(subset=["Open", "High", "Low", "Close"])
    )

    return resampled


def build_mtf(
    base_df: pd.DataFrame,
    timeframes: list[str],
) -> dict[str, pd.DataFrame]:
    """
    Build multiple higher-timeframe views from a single base DataFrame.

    Args:
        base_df:    Base OHLCV DataFrame (finest granularity available).
        timeframes: List of target timeframe strings, e.g. ["1h", "4h"].

    Returns:
        Dict keyed by timeframe string. The base timeframe is included as-is
        if its string is provided; higher ones are resampled.

    Example:
        data = fetch_ohlcv("EURUSD", "15m", start="2023-01-01")
        mtf = build_mtf(data, ["15m", "1h", "4h"])
        # mtf["15m"] → raw 15-min data
        # mtf["1h"]  → resampled 1-hour data
        # mtf["4h"]  → resampled 4-hour data
    """
    result: dict[str, pd.DataFrame] = {}
    for tf in timeframes:
        if _is_same_or_coarser(base_df, tf):
            result[tf] = resample(base_df, tf)
        else:
            # tf is finer than the base — return as-is (caller's responsibility)
            result[tf] = base_df.copy()
    return result


def _is_same_or_coarser(df: pd.DataFrame, tf: str) -> bool:
    """
    Returns True if the target timeframe is coarser than or equal to the
    DataFrame's detected frequency. Used to decide whether to resample.
    """
    if len(df) < 2:
        return True

    detected_seconds = (df.index[1] - df.index[0]).total_seconds()
    target_seconds = _tf_to_seconds(tf)

    return target_seconds >= detected_seconds


def _tf_to_seconds(tf: str) -> int:
    """Convert a timeframe string to approximate seconds for comparison."""
    mapping = {
        "1m": 60,
        "2m": 120,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "60m": 3600,
        "90m": 5400,
        "4h": 14400,
        "1d": 86400,
        "1wk": 604800,
    }
    return mapping.get(tf, 0)


def align_to_htf_close(ltf_df: pd.DataFrame, htf_df: pd.DataFrame) -> pd.DataFrame:
    """
    Forward-fill the latest confirmed HTF candle onto each LTF bar.

    Used to attach the HTF bias to each LTF candle without look-ahead:
    the HTF close is only available after the HTF candle closes, so we
    use shift(1) on the HTF data before merging.

    Returns the LTF DataFrame with additional columns:
        htf_open, htf_high, htf_low, htf_close
    """
    htf_shifted = htf_df[["Open", "High", "Low", "Close"]].shift(1)
    htf_shifted.columns = ["htf_open", "htf_high", "htf_low", "htf_close"]

    merged = ltf_df.copy()
    merged = merged.join(htf_shifted, how="left")
    merged[["htf_open", "htf_high", "htf_low", "htf_close"]] = (
        merged[["htf_open", "htf_high", "htf_low", "htf_close"]].ffill()
    )
    return merged
