"""
OHLCV data fetching layer.

Returns a standardised DataFrame (columns: Open, High, Low, Close, Volume)
with a UTC-aware DatetimeIndex regardless of the underlying source.
All consumers (detectors, backtest engine) depend on this contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Canonical OHLCV column names used everywhere in this project
OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# yfinance ticker symbols for each pair
_TICKER_MAP: dict[str, str] = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
}

# Valid timeframe strings accepted by yfinance
_VALID_TIMEFRAMES = {
    "1m", "2m", "5m", "15m", "30m",
    "60m", "90m", "1h", "4h",
    "1d", "5d", "1wk", "1mo",
}

# yfinance caps intraday history depending on interval
_INTRADAY_HISTORY_LIMIT: dict[str, int] = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1h": 730,
}


class DataSource(Enum):
    YFINANCE = "yfinance"
    # OANDA = "oanda"  # placeholder for Phase 5


def fetch_ohlcv(
    pair: str,
    timeframe: str,
    start: Optional[str | datetime] = None,
    end: Optional[str | datetime] = None,
    source: DataSource = DataSource.YFINANCE,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for a Forex pair.

    Args:
        pair:      Pair symbol, e.g. "EURUSD", "GBPUSD", "USDJPY"
        timeframe: Timeframe string, e.g. "15m", "1h", "4h", "1d"
        start:     Start date (ISO string or datetime). Required for daily/weekly TFs.
        end:       End date (ISO string or datetime). Defaults to now.
        source:    Data source backend.

    Returns:
        DataFrame with columns [Open, High, Low, Close, Volume] and UTC DatetimeIndex.
        Never returns an empty DataFrame without raising — raises ValueError instead.

    Raises:
        ValueError: unknown pair, invalid timeframe, or no data returned.
    """
    pair = pair.upper()
    if pair not in _TICKER_MAP:
        raise ValueError(f"Unknown pair '{pair}'. Supported: {list(_TICKER_MAP)}")
    if timeframe not in _VALID_TIMEFRAMES:
        raise ValueError(f"Invalid timeframe '{timeframe}'. Supported: {_VALID_TIMEFRAMES}")

    if source == DataSource.YFINANCE:
        return _fetch_yfinance(pair, timeframe, start, end)

    raise NotImplementedError(f"Data source '{source}' is not yet implemented.")


def _fetch_yfinance(
    pair: str,
    timeframe: str,
    start: Optional[str | datetime],
    end: Optional[str | datetime],
) -> pd.DataFrame:
    ticker = _TICKER_MAP[pair]
    logger.info("Fetching %s %s from yfinance (start=%s, end=%s)", pair, timeframe, start, end)

    kwargs: dict = {"interval": timeframe, "progress": False, "auto_adjust": True}

    if start is not None:
        kwargs["start"] = start
        kwargs["end"] = end or datetime.now(timezone.utc)
    else:
        # Use period-based fetch when no explicit start given
        limit_days = _INTRADAY_HISTORY_LIMIT.get(timeframe)
        if limit_days:
            kwargs["period"] = f"{limit_days}d"
        else:
            kwargs["period"] = "max"

    raw: pd.DataFrame = yf.download(ticker, **kwargs)

    if raw.empty:
        raise ValueError(
            f"No data returned for {pair} ({timeframe}). "
            "Check pair symbol, timeframe, and date range."
        )

    df = _normalise(raw)
    logger.info("Fetched %d candles for %s %s", len(df), pair, timeframe)
    return df


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise a raw yfinance DataFrame to the project's canonical format:
    - Columns: Open, High, Low, Close, Volume
    - Index: UTC-aware DatetimeIndex, ascending, no duplicates
    """
    # yfinance sometimes returns MultiIndex columns (ticker, field) — flatten
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # Keep only the columns we need; add Volume=0 if absent (some FX feeds omit it)
    available = [c for c in OHLCV_COLUMNS if c in raw.columns]
    df = raw[available].copy()
    if "Volume" not in df.columns:
        df["Volume"] = 0.0

    df = df[OHLCV_COLUMNS]

    # Ensure UTC-aware index
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)

    return df


def fetch_multi_timeframe(
    pair: str,
    timeframes: list[str],
    start: Optional[str | datetime] = None,
    end: Optional[str | datetime] = None,
    source: DataSource = DataSource.YFINANCE,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for multiple timeframes in one call.

    Returns a dict keyed by timeframe string, e.g.:
        {"15m": df_15m, "1h": df_1h, "4h": df_4h}
    """
    return {
        tf: fetch_ohlcv(pair, tf, start=start, end=end, source=source)
        for tf in timeframes
    }
