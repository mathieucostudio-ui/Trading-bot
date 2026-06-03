"""
Session tagging: Kill Zones, Asian Range, AMD phase detection.

All session windows are defined in America/New_York (EST/EDT).
DST transitions are handled automatically by pytz.
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd
import pytz

_EST = pytz.timezone("America/New_York")

# Session windows (EST), keyed by session name
_SESSION_WINDOWS: dict[str, tuple[time, time]] = {
    "asian":        (time(19, 0), time(22, 0)),
    "london":       (time(2, 0),  time(5, 0)),
    "new_york":     (time(8, 0),  time(11, 0)),
    "london_close": (time(11, 0), time(13, 0)),
}

# Sessions that constitute a Kill Zone (institutional activity peak)
_KILL_ZONE_SESSIONS = frozenset({"london", "new_york"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full session analysis pipeline.

    Added columns:
        session      : str  — 'asian' | 'london' | 'new_york' | 'london_close' | 'off'
        in_kill_zone : bool — True during London or New York Kill Zones
        ar_high      : float — Asian Range high from the most recent Asian session
        ar_low       : float — Asian Range low from the most recent Asian session
        amd_phase    : int  — 0=unknown | 1=accumulation | 2=manipulation | 3=distribution

    Args:
        df: OHLCV DataFrame with UTC DatetimeIndex.

    Returns:
        Copy of df with session columns added.
    """
    df = df.copy()
    df = _tag_sessions(df)
    df = _compute_asian_range(df)
    df = _tag_amd_phases(df)
    return df


def in_kill_zone(ts: pd.Timestamp) -> bool:
    """Return True if the given UTC timestamp falls within a Kill Zone."""
    local = ts.tz_convert(_EST) if ts.tzinfo else ts.tz_localize("UTC").tz_convert(_EST)
    t = local.time()
    for session in _KILL_ZONE_SESSIONS:
        start, end = _SESSION_WINDOWS[session]
        if start <= t < end:
            return True
    return False


# ---------------------------------------------------------------------------
# Session tagging
# ---------------------------------------------------------------------------

def _to_est(df: pd.DataFrame) -> pd.DatetimeIndex:
    if df.index.tzinfo is None:
        return df.index.tz_localize("UTC").tz_convert(_EST)
    return df.index.tz_convert(_EST)


def _tag_sessions(df: pd.DataFrame) -> pd.DataFrame:
    est_idx = _to_est(df)
    est_times = np.array([ts.time() for ts in est_idx])

    session_col = np.full(len(df), "off", dtype=object)

    for name, (start, end) in _SESSION_WINDOWS.items():
        if start < end:
            mask = np.array([start <= t < end for t in est_times])
        else:
            # Spans midnight (e.g., 22:00–02:00 would, but none of ours do)
            mask = np.array([t >= start or t < end for t in est_times])
        session_col[mask] = name

    df["session"] = session_col
    df["in_kill_zone"] = np.isin(df["session"].values, list(_KILL_ZONE_SESSIONS))
    return df


# ---------------------------------------------------------------------------
# Asian Range
# ---------------------------------------------------------------------------

def _compute_asian_range(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach ar_high / ar_low to every bar.

    The Asian Range for a given London session is defined by the prior
    Asian session (19:00–22:00 EST). We compute it per calendar date
    (EST), then forward-fill onto subsequent bars.
    """
    est_idx = _to_est(df)
    est_dates = np.array([ts.date() for ts in est_idx])

    asian_mask = df["session"].values == "asian"

    ar_high = np.full(len(df), np.nan)
    ar_low  = np.full(len(df), np.nan)

    if not asian_mask.any():
        df["ar_high"] = ar_high
        df["ar_low"]  = ar_low
        return df

    # Build Asian Range per date
    asian_dates  = est_dates[asian_mask]
    asian_highs  = df["High"].values[asian_mask]
    asian_lows   = df["Low"].values[asian_mask]

    date_range_high: dict = {}
    date_range_low: dict  = {}
    for d, h, l in zip(asian_dates, asian_highs, asian_lows):
        date_range_high[d] = max(date_range_high.get(d, -np.inf), h)
        date_range_low[d]  = min(date_range_low.get(d, np.inf), l)

    # Assign each bar the Asian Range from the same calendar date
    # (for London/NY bars the next morning this equals the prior evening's range)
    for i, d in enumerate(est_dates):
        if d in date_range_high:
            ar_high[i] = date_range_high[d]
            ar_low[i]  = date_range_low[d]

    # Forward-fill so NY / London-close bars also carry the range
    ar_high_s = pd.Series(ar_high).ffill().values
    ar_low_s  = pd.Series(ar_low).ffill().values

    df["ar_high"] = ar_high_s
    df["ar_low"]  = ar_low_s
    return df


# ---------------------------------------------------------------------------
# AMD phase tagging
# ---------------------------------------------------------------------------

def _tag_amd_phases(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign AMD phase (0=unknown, 1=accumulation, 2=manipulation, 3=distribution).

    Rules:
      Phase 1 (Accumulation) : Asian session bars
      Phase 2 (Manipulation) : First London bar that sweeps the Asian Range high OR low
                               (wick beyond the level but close does not confirm breakout)
      Phase 3 (Distribution) : Remaining London / NY bars after Phase 2 sweep confirmed
    """
    n = len(df)
    amd = np.zeros(n, dtype=int)

    sessions  = df["session"].values
    ar_highs  = df["ar_high"].values
    ar_lows   = df["ar_low"].values
    highs     = df["High"].values
    lows      = df["Low"].values
    closes    = df["Close"].values

    # Phase 1: Asian session
    amd[sessions == "asian"] = 1

    # Phase 2 / 3: London session — detect manipulation sweep
    london_mask = sessions == "london"
    london_idx  = np.where(london_mask)[0]

    # Group London bars by trading day (reset each day)
    est_idx = _to_est(df)
    est_dates = np.array([ts.date() for ts in est_idx])

    seen_days: set = set()
    manip_done: dict = {}   # date → bool

    for i in london_idx:
        day = est_dates[i]
        ar_h = ar_highs[i]
        ar_l = ar_lows[i]

        if np.isnan(ar_h) or np.isnan(ar_l):
            continue

        if day not in seen_days:
            seen_days.add(day)
            manip_done[day] = False

        if not manip_done[day]:
            # Check for sweep: wick beyond AR, close back inside
            swept_high = highs[i] > ar_h and closes[i] <= ar_h
            swept_low  = lows[i]  < ar_l and closes[i] >= ar_l

            if swept_high or swept_low:
                amd[i] = 2
                manip_done[day] = True
            else:
                amd[i] = 1   # still accumulation-like until sweep
        else:
            amd[i] = 3       # distribution after sweep

    # Phase 3 continues into NY session after manipulation is done
    ny_mask = sessions == "new_york"
    ny_idx  = np.where(ny_mask)[0]
    for i in ny_idx:
        day = est_dates[i]
        if manip_done.get(day, False):
            amd[i] = 3

    df["amd_phase"] = amd
    return df
