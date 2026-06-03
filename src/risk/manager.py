"""
Risk Manager: SL/TP placement and position sizing for ICT/SMC entries.

ICT Stop Loss placement rules:
  - Long  : SL below the Order Block bottom (or swing low if no OB available),
            with an additional buffer (default 0.1% of price).
  - Short : SL above the Order Block top (or swing high if no OB available),
            with an additional buffer.

Take Profit:
  TP = entry ± (entry − SL) × rr_ratio

Position sizing (fixed fractional, 1% risk rule):
  size = (account_balance × risk_pct) / |entry − stop_loss|

  This gives the number of units (e.g., standard lots for FX must then be
  divided by pip_value depending on broker/pair, which is broker-specific).
  The output here is in "price units" — multiply by pip_factor downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from detectors.orderblock import OrderBlock
from strategy.signal import TradeSignal


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RiskConfig:
    account_balance: float = 10_000.0   # USD
    risk_pct: float = 0.01              # 1 % per trade
    rr_ratio: float = 2.0               # 2 : 1 reward : risk
    sl_buffer_pct: float = 0.001        # 0.1 % buffer beyond OB/swing
    max_concurrent: int = 3             # maximum open trades at once


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class SizedSignal:
    """A TradeSignal enriched with SL, TP, and position size."""
    signal: TradeSignal
    stop_loss: float
    take_profit: float
    risk_amount: float     # USD at risk on this trade
    size_units: float      # position size in price-units (broker conversion needed)

    @property
    def direction(self) -> str:
        return self.signal.direction

    @property
    def entry_price(self) -> float:
        return self.signal.entry_price

    @property
    def rr_actual(self) -> float:
        return abs(self.take_profit - self.entry_price) / abs(self.entry_price - self.stop_loss)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_risk(
    signals: list[TradeSignal],
    df: pd.DataFrame,
    obs: list[OrderBlock],
    config: Optional[RiskConfig] = None,
) -> list[SizedSignal]:
    """
    Attach SL, TP, and position size to each raw signal.

    Args:
        signals: Output from generate_signals().
        df:      Enriched pipeline DataFrame (needs last_sh, last_sl columns).
        obs:     OrderBlock list from the pipeline (used for precise SL levels).
        config:  RiskConfig; uses defaults if None.

    Returns:
        List of SizedSignal objects (invalid signals — e.g., zero risk — are dropped).
    """
    if config is None:
        config = RiskConfig()

    _require_columns(df)
    last_sh = df["last_sh"].values
    last_sl = df["last_sl"].values

    sized: list[SizedSignal] = []

    for sig in signals:
        i = sig.bar_index
        entry = sig.entry_price

        sl = _compute_sl(sig, i, df, obs, last_sh, last_sl, config)
        if sl is None:
            continue

        risk_per_unit = abs(entry - sl)
        if risk_per_unit <= 0:
            continue

        tp = _compute_tp(entry, sl, sig.direction, config.rr_ratio)
        risk_amount = config.account_balance * config.risk_pct
        size_units  = risk_amount / risk_per_unit

        sized_sig = SizedSignal(
            signal=sig,
            stop_loss=sl,
            take_profit=tp,
            risk_amount=risk_amount,
            size_units=size_units,
        )
        # Back-populate onto the original signal object too
        sig.stop_loss   = sl
        sig.take_profit = tp
        sig.size_units  = size_units

        sized.append(sized_sig)

    return sized


def validate_config(config: RiskConfig) -> list[str]:
    """Return a list of validation error strings (empty means valid)."""
    errors: list[str] = []
    if config.account_balance <= 0:
        errors.append("account_balance must be positive")
    if not (0 < config.risk_pct <= 0.05):
        errors.append("risk_pct must be in (0, 0.05] — max 5% per trade")
    if config.rr_ratio < 1.0:
        errors.append("rr_ratio must be >= 1.0")
    if config.sl_buffer_pct < 0:
        errors.append("sl_buffer_pct must be >= 0")
    if config.max_concurrent < 1:
        errors.append("max_concurrent must be >= 1")
    return errors


# ---------------------------------------------------------------------------
# SL / TP helpers
# ---------------------------------------------------------------------------

def _compute_sl(
    sig: TradeSignal,
    i: int,
    df: pd.DataFrame,
    obs: list[OrderBlock],
    last_sh: np.ndarray,
    last_sl: np.ndarray,
    config: RiskConfig,
) -> Optional[float]:
    """
    Determine stop loss level for a signal.

    Priority:
      1. Most recent non-mitigated OB in the signal direction (precise ICT SL)
      2. Structural swing high/low (last_sh / last_sl)
      3. Fallback: entry ± 2× sl_buffer (guarantees a valid SL exists)
    """
    buffer = sig.entry_price * config.sl_buffer_pct

    if sig.direction == "long":
        # Best OB: latest bull OB whose zone is below entry and not mitigated
        ob_level = _best_ob_sl(obs, kind="bull", entry=sig.entry_price, bar_i=i)
        if ob_level is not None:
            return ob_level - buffer

        # Structural swing low
        sl_struct = last_sl[i]
        if not np.isnan(sl_struct) and sl_struct < sig.entry_price:
            return float(sl_struct) - buffer

        # Fallback
        return sig.entry_price - 2 * buffer

    else:  # short
        ob_level = _best_ob_sl(obs, kind="bear", entry=sig.entry_price, bar_i=i)
        if ob_level is not None:
            return ob_level + buffer

        sh_struct = last_sh[i]
        if not np.isnan(sh_struct) and sh_struct > sig.entry_price:
            return float(sh_struct) + buffer

        return sig.entry_price + 2 * buffer


def _best_ob_sl(
    obs: list[OrderBlock],
    kind: str,
    entry: float,
    bar_i: int,
) -> Optional[float]:
    """
    Find the bottom (bull OB) or top (bear OB) of the most recent valid OB
    that sits on the correct side of the entry price.
    """
    candidates = [
        o for o in obs
        if o.kind == kind
        and not o.mitigated
        and not o.is_breaker
        and o.bar_index <= bar_i
    ]
    if not candidates:
        return None

    # Most recent first
    candidates.sort(key=lambda o: o.bar_index, reverse=True)

    for ob in candidates:
        if kind == "bull" and ob.bottom < entry:
            return ob.bottom
        if kind == "bear" and ob.top > entry:
            return ob.top

    return None


def _compute_tp(entry: float, sl: float, direction: str, rr: float) -> float:
    risk = abs(entry - sl)
    if direction == "long":
        return entry + risk * rr
    return entry - risk * rr


# ---------------------------------------------------------------------------
# Column validation
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame) -> None:
    for col in ("last_sh", "last_sl"):
        if col not in df.columns:
            raise ValueError(
                f"Column '{col}' missing — run detect_structure() before apply_risk()."
            )
