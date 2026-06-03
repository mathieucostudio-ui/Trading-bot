"""
Unit tests for src/data/fetcher.py

These tests use synthetic DataFrames to avoid network calls.
The yfinance download is monkeypatched so tests run offline.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data.fetcher import (
    OHLCV_COLUMNS,
    DataSource,
    _normalise,
    fetch_ohlcv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw(n: int = 10, tz: str | None = "UTC") -> pd.DataFrame:
    """Build a minimal raw OHLCV DataFrame mimicking yfinance output."""
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz=tz)
    return pd.DataFrame(
        {
            "Open":   [1.1000 + i * 0.0001 for i in range(n)],
            "High":   [1.1010 + i * 0.0001 for i in range(n)],
            "Low":    [1.0990 + i * 0.0001 for i in range(n)],
            "Close":  [1.1005 + i * 0.0001 for i in range(n)],
            "Volume": [1000.0] * n,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_returns_canonical_columns(self):
        raw = _make_raw()
        df = _normalise(raw)
        assert list(df.columns) == OHLCV_COLUMNS

    def test_index_is_utc(self):
        raw = _make_raw(tz=None)  # tz-naive input
        df = _normalise(raw)
        assert df.index.tzinfo is not None
        assert str(df.index.tzinfo) == "UTC"

    def test_converts_non_utc_tz_to_utc(self):
        raw = _make_raw(tz="America/New_York")
        df = _normalise(raw)
        assert str(df.index.tzinfo) == "UTC"

    def test_no_duplicates_in_index(self):
        raw = _make_raw()
        # Introduce a duplicate row
        raw = pd.concat([raw, raw.iloc[[0]]])
        df = _normalise(raw)
        assert not df.index.duplicated().any()

    def test_drops_rows_with_nan_ohlc(self):
        raw = _make_raw(5)
        raw.loc[raw.index[2], "Close"] = float("nan")
        df = _normalise(raw)
        assert len(df) == 4

    def test_adds_volume_column_if_missing(self):
        raw = _make_raw().drop(columns=["Volume"])
        df = _normalise(raw)
        assert "Volume" in df.columns
        assert (df["Volume"] == 0.0).all()

    def test_multiindex_columns_flattened(self):
        raw = _make_raw()
        raw.columns = pd.MultiIndex.from_tuples(
            [(c, "EURUSD=X") for c in raw.columns]
        )
        df = _normalise(raw)
        assert isinstance(df.columns, pd.Index)
        assert list(df.columns) == OHLCV_COLUMNS


# ---------------------------------------------------------------------------
# fetch_ohlcv — error handling (no network)
# ---------------------------------------------------------------------------

class TestFetchOhlcvValidation:
    def test_raises_on_unknown_pair(self):
        with pytest.raises(ValueError, match="Unknown pair"):
            fetch_ohlcv("XYZABC", "15m")

    def test_raises_on_invalid_timeframe(self):
        with pytest.raises(ValueError, match="Invalid timeframe"):
            fetch_ohlcv("EURUSD", "99x")

    def test_raises_on_unsupported_source(self, monkeypatch):
        # Bypass enum validation to reach the NotImplementedError branch
        import data.fetcher as fetcher_module
        with pytest.raises((ValueError, NotImplementedError)):
            fetch_ohlcv("EURUSD", "15m", source="fake_source")  # type: ignore


# ---------------------------------------------------------------------------
# fetch_ohlcv — monkeypatched happy path
# ---------------------------------------------------------------------------

class TestFetchOhlcvHappyPath:
    def test_returns_canonical_dataframe(self, monkeypatch):
        raw = _make_raw(100)

        import yfinance as yf
        monkeypatch.setattr(yf, "download", lambda *a, **kw: raw)

        df = fetch_ohlcv("EURUSD", "15m")

        assert list(df.columns) == OHLCV_COLUMNS
        assert len(df) == 100
        assert df.index.tzinfo is not None

    def test_raises_when_download_returns_empty(self, monkeypatch):
        import yfinance as yf
        monkeypatch.setattr(yf, "download", lambda *a, **kw: pd.DataFrame())

        with pytest.raises(ValueError, match="No data returned"):
            fetch_ohlcv("EURUSD", "15m")

    def test_all_supported_pairs(self, monkeypatch):
        raw = _make_raw(50)
        import yfinance as yf
        monkeypatch.setattr(yf, "download", lambda *a, **kw: raw)

        for pair in ("EURUSD", "GBPUSD", "USDJPY"):
            df = fetch_ohlcv(pair, "15m")
            assert not df.empty, f"Empty result for {pair}"
