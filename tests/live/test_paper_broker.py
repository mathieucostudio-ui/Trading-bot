"""
Tests pour src/live/paper_broker.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from live.paper_broker import PaperBroker, PaperPosition
from risk.manager import RiskConfig, SizedSignal
from strategy.signal import TradeSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sized_signal(
    direction: str = "long",
    entry: float = 1.1000,
    sl: float = 1.0950,
    tp: float = 1.1100,
) -> SizedSignal:
    idx = pd.date_range("2024-01-08 09:00", periods=5, freq="15min", tz="UTC")
    sig = TradeSignal(
        direction=direction,
        bar_index=4,
        timestamp=idx[4],
        entry_price=entry,
        confluence_score=4,
        amd_phase=3,
    )
    return SizedSignal(
        signal=sig,
        stop_loss=sl,
        take_profit=tp,
        risk_amount=100.0,
        size_units=20_000.0,
    )


def _broker(balance: float = 10_000.0, max_concurrent: int = 3) -> PaperBroker:
    with patch("live.paper_broker.LOGS_DIR", Path(tempfile.mkdtemp())):
        b = PaperBroker(initial_balance=balance, max_concurrent=max_concurrent)
        b._log_dir = Path(tempfile.mkdtemp())
        return b


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_initial_balance(self):
        b = _broker(10_000.0)
        assert b.balance == 10_000.0

    def test_no_open_positions(self):
        b = _broker()
        assert b.open_positions == []

    def test_no_closed_positions(self):
        b = _broker()
        assert b.closed_positions == []


# ---------------------------------------------------------------------------
# Ouverture de position
# ---------------------------------------------------------------------------

class TestOpenPosition:
    def test_opens_position(self):
        b = _broker()
        ss = _sized_signal()
        pos = b.open_position(ss, "EURUSD")
        assert pos is not None
        assert pos.is_open

    def test_position_in_open_list(self):
        b = _broker()
        b.open_position(_sized_signal(), "EURUSD")
        assert len(b.open_positions) == 1

    def test_direction_stored(self):
        b = _broker()
        pos = b.open_position(_sized_signal("long"), "EURUSD")
        assert pos.direction == "long"

    def test_entry_price_stored(self):
        b = _broker()
        pos = b.open_position(_sized_signal(entry=1.1000), "EURUSD")
        assert pos.entry_price == pytest.approx(1.1000)

    def test_max_concurrent_blocks(self):
        b = _broker(max_concurrent=1)
        b.open_position(_sized_signal(), "EURUSD")
        pos2 = b.open_position(_sized_signal(), "GBPUSD")
        assert pos2 is None

    def test_one_position_per_pair(self):
        b = _broker(max_concurrent=3)
        b.open_position(_sized_signal(), "EURUSD")
        pos2 = b.open_position(_sized_signal(), "EURUSD")
        assert pos2 is None


# ---------------------------------------------------------------------------
# Mise à jour SL/TP
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_tp_closes_long(self):
        b = _broker()
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        closed = b.update("EURUSD", high=1.13, low=1.10, close=1.12)
        assert len(closed) == 1
        assert closed[0].exit_reason == "tp"

    def test_sl_closes_long(self):
        b = _broker()
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        closed = b.update("EURUSD", high=1.105, low=1.085, close=1.09)
        assert len(closed) == 1
        assert closed[0].exit_reason == "sl"

    def test_tp_closes_short(self):
        b = _broker()
        b.open_position(_sized_signal("short", entry=1.10, sl=1.11, tp=1.08), "EURUSD")
        closed = b.update("EURUSD", high=1.105, low=1.075, close=1.08)
        assert len(closed) == 1
        assert closed[0].exit_reason == "tp"

    def test_sl_closes_short(self):
        b = _broker()
        b.open_position(_sized_signal("short", entry=1.10, sl=1.11, tp=1.08), "EURUSD")
        closed = b.update("EURUSD", high=1.115, low=1.095, close=1.11)
        assert len(closed) == 1
        assert closed[0].exit_reason == "sl"

    def test_no_close_when_price_in_range(self):
        b = _broker()
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        closed = b.update("EURUSD", high=1.105, low=1.095, close=1.102)
        assert closed == []

    def test_tp_pnl_positive_for_long(self):
        b = _broker()
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        closed = b.update("EURUSD", high=1.13, low=1.10, close=1.12)
        assert closed[0].pnl > 0

    def test_sl_pnl_negative_for_long(self):
        b = _broker()
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        closed = b.update("EURUSD", high=1.095, low=1.085, close=1.09)
        assert closed[0].pnl < 0

    def test_balance_updated_after_close(self):
        b = _broker(10_000.0)
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        b.update("EURUSD", high=1.13, low=1.10, close=1.12)
        assert b.balance != 10_000.0

    def test_no_update_for_different_pair(self):
        b = _broker()
        b.open_position(_sized_signal("long", entry=1.10, sl=1.09, tp=1.12), "EURUSD")
        closed = b.update("GBPUSD", high=1.13, low=1.08, close=1.12)
        assert closed == []
        assert len(b.open_positions) == 1


# ---------------------------------------------------------------------------
# PaperPosition
# ---------------------------------------------------------------------------

class TestPaperPosition:
    def test_is_open_true_initially(self):
        pos = PaperPosition(
            id="PT0001", pair="EURUSD", direction="long",
            entry_price=1.10, stop_loss=1.09, take_profit=1.12,
            size_units=10_000.0, entry_time="2024-01-08T09:00:00+00:00",
            confluence_score=4,
        )
        assert pos.is_open

    def test_close_sets_exit_fields(self):
        pos = PaperPosition(
            id="PT0001", pair="EURUSD", direction="long",
            entry_price=1.10, stop_loss=1.09, take_profit=1.12,
            size_units=10_000.0, entry_time="2024-01-08T09:00:00+00:00",
            confluence_score=4,
        )
        pos.close(1.12, "2024-01-08T10:00:00+00:00", "tp")
        assert not pos.is_open
        assert pos.exit_reason == "tp"
        assert pos.pnl == pytest.approx((1.12 - 1.10) * 10_000.0)
