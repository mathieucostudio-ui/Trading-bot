"""
Tests for src/risk/manager.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from detectors.orderblock import OrderBlock
from strategy.signal import TradeSignal
from risk.manager import RiskConfig, SizedSignal, apply_risk, validate_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _structure_df(n: int = 10, last_sh: float = 1.15, last_sl: float = 1.05) -> pd.DataFrame:
    """Minimal DataFrame with last_sh / last_sl columns required by apply_risk."""
    idx = pd.date_range("2024-01-08 08:00", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "Open":   [1.10] * n,
        "High":   [1.15] * n,
        "Low":    [1.05] * n,
        "Close":  [1.10] * n,
        "Volume": [1.0]  * n,
        "last_sh": [last_sh] * n,
        "last_sl": [last_sl] * n,
    }, index=idx)


def _long_signal(bar_index: int = 5, entry: float = 1.10) -> TradeSignal:
    idx = pd.date_range("2024-01-08 08:00", periods=10, freq="15min", tz="UTC")
    return TradeSignal(
        direction="long",
        bar_index=bar_index,
        timestamp=idx[bar_index],
        entry_price=entry,
        confluence_score=4,
        amd_phase=3,
    )


def _short_signal(bar_index: int = 5, entry: float = 1.10) -> TradeSignal:
    idx = pd.date_range("2024-01-08 08:00", periods=10, freq="15min", tz="UTC")
    return TradeSignal(
        direction="short",
        bar_index=bar_index,
        timestamp=idx[bar_index],
        entry_price=entry,
        confluence_score=4,
        amd_phase=3,
    )


def _bull_ob(bottom: float = 1.06, top: float = 1.08, bar_index: int = 3) -> OrderBlock:
    return OrderBlock(
        kind="bull",
        top=top,
        bottom=bottom,
        bar_index=bar_index,
        timestamp=pd.Timestamp("2024-01-08 08:45", tz="UTC"),
        bos_index=6,
    )


def _bear_ob(bottom: float = 1.12, top: float = 1.14, bar_index: int = 3) -> OrderBlock:
    return OrderBlock(
        kind="bear",
        top=top,
        bottom=bottom,
        bar_index=bar_index,
        timestamp=pd.Timestamp("2024-01-08 08:45", tz="UTC"),
        bos_index=6,
    )


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

class TestValidateConfig:
    def test_default_config_valid(self):
        cfg = RiskConfig()
        assert validate_config(cfg) == []

    def test_negative_balance_invalid(self):
        cfg = RiskConfig(account_balance=-1)
        errors = validate_config(cfg)
        assert any("account_balance" in e for e in errors)

    def test_zero_balance_invalid(self):
        errors = validate_config(RiskConfig(account_balance=0))
        assert len(errors) > 0

    def test_risk_pct_too_high_invalid(self):
        errors = validate_config(RiskConfig(risk_pct=0.10))
        assert any("risk_pct" in e for e in errors)

    def test_rr_below_1_invalid(self):
        errors = validate_config(RiskConfig(rr_ratio=0.5))
        assert any("rr_ratio" in e for e in errors)

    def test_negative_buffer_invalid(self):
        errors = validate_config(RiskConfig(sl_buffer_pct=-0.001))
        assert any("sl_buffer_pct" in e for e in errors)

    def test_zero_concurrent_invalid(self):
        errors = validate_config(RiskConfig(max_concurrent=0))
        assert any("max_concurrent" in e for e in errors)


# ---------------------------------------------------------------------------
# apply_risk — output schema
# ---------------------------------------------------------------------------

class TestApplyRiskSchema:
    def test_returns_list(self):
        df  = _structure_df()
        sig = _long_signal()
        result = apply_risk([sig], df, obs=[])
        assert isinstance(result, list)

    def test_all_sized_signals(self):
        df  = _structure_df()
        sig = _long_signal()
        result = apply_risk([sig], df, obs=[])
        assert all(isinstance(s, SizedSignal) for s in result)

    def test_requires_structure_columns(self):
        df = pd.DataFrame({"Open": [1.0], "Close": [1.0]})
        with pytest.raises(ValueError, match="last_sh"):
            apply_risk([_long_signal()], df, obs=[])


# ---------------------------------------------------------------------------
# SL / TP correctness
# ---------------------------------------------------------------------------

class TestSLTP:
    def test_long_sl_below_entry(self):
        df  = _structure_df()
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bull_ob()])
        assert sized.stop_loss < sized.entry_price

    def test_short_sl_above_entry(self):
        df  = _structure_df()
        sig = _short_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bear_ob()])
        assert sized.stop_loss > sized.entry_price

    def test_long_tp_above_entry(self):
        df  = _structure_df()
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bull_ob()])
        assert sized.take_profit > sized.entry_price

    def test_short_tp_below_entry(self):
        df  = _structure_df()
        sig = _short_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bear_ob()])
        assert sized.take_profit < sized.entry_price

    def test_rr_ratio_respected(self):
        cfg = RiskConfig(rr_ratio=2.0)
        df  = _structure_df()
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bull_ob()], config=cfg)
        assert sized.rr_actual == pytest.approx(2.0, rel=0.01)

    def test_sl_uses_ob_bottom_for_long(self):
        """Long SL should be placed below the bull OB bottom (minus buffer)."""
        cfg = RiskConfig(sl_buffer_pct=0.001)
        df  = _structure_df()
        ob  = _bull_ob(bottom=1.060, top=1.080)
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[ob], config=cfg)
        expected_sl = 1.060 - 1.10 * 0.001
        assert sized.stop_loss == pytest.approx(expected_sl, rel=0.001)

    def test_sl_uses_ob_top_for_short(self):
        """Short SL should be placed above the bear OB top (plus buffer)."""
        cfg = RiskConfig(sl_buffer_pct=0.001)
        df  = _structure_df()
        ob  = _bear_ob(bottom=1.120, top=1.140)
        sig = _short_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[ob], config=cfg)
        expected_sl = 1.140 + 1.10 * 0.001
        assert sized.stop_loss == pytest.approx(expected_sl, rel=0.001)

    def test_sl_falls_back_to_structural_level(self):
        """Without any OB, SL should use last_sl (for long)."""
        df  = _structure_df(last_sl=1.04)
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[])
        assert sized.stop_loss < 1.10
        assert sized.stop_loss < 1.04 + 0.01   # at or below structural low


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def test_risk_amount_equals_balance_times_risk_pct(self):
        cfg = RiskConfig(account_balance=10_000, risk_pct=0.01)
        df  = _structure_df()
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bull_ob()], config=cfg)
        assert sized.risk_amount == pytest.approx(100.0)

    def test_size_units_positive(self):
        df  = _structure_df()
        sig = _long_signal()
        (sized,) = apply_risk([sig], df, obs=[_bull_ob()])
        assert sized.size_units > 0

    def test_larger_risk_pct_gives_larger_position(self):
        df   = _structure_df()
        sig1 = _long_signal()
        sig2 = _long_signal()
        cfg1 = RiskConfig(risk_pct=0.01)
        cfg2 = RiskConfig(risk_pct=0.02)
        (s1,) = apply_risk([sig1], df, obs=[_bull_ob()], config=cfg1)
        (s2,) = apply_risk([sig2], df, obs=[_bull_ob()], config=cfg2)
        assert s2.size_units > s1.size_units

    def test_mitigated_ob_not_used_for_sl(self):
        """A mitigated OB must not be selected as the SL anchor."""
        df = _structure_df(last_sl=1.04)
        ob = _bull_ob(bottom=1.06, top=1.08)
        ob.mitigated = True
        ob.mitigation_index = 8
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[ob])
        # SL should fall back to structural level, not OB bottom
        assert sized.stop_loss < 1.06  # below structural low, not OB bottom


# ---------------------------------------------------------------------------
# SizedSignal properties
# ---------------------------------------------------------------------------

class TestSizedSignalProperties:
    def _make_sized(self) -> SizedSignal:
        df  = _structure_df()
        sig = _long_signal(entry=1.10)
        (sized,) = apply_risk([sig], df, obs=[_bull_ob()])
        return sized

    def test_direction_delegates_to_signal(self):
        assert self._make_sized().direction == "long"

    def test_entry_price_delegates_to_signal(self):
        assert self._make_sized().entry_price == pytest.approx(1.10)
