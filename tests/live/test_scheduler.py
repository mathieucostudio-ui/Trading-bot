"""
Tests pour src/live/scheduler.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import pytz

from live.scheduler import (
    in_kill_zone,
    next_kill_zone_start,
    seconds_until_next_kill_zone,
    run_scheduler,
)

_EST = pytz.timezone("America/New_York")


def _est(hour: int, minute: int = 0) -> datetime:
    """Crée un datetime EST à l'heure donnée."""
    naive = datetime(2024, 1, 8, hour, minute, 0)
    return _EST.localize(naive)


# ---------------------------------------------------------------------------
# in_kill_zone
# ---------------------------------------------------------------------------

class TestInKillZone:
    def test_london_02h_is_in_kz(self):
        assert in_kill_zone(_est(2, 30)) is True

    def test_london_05h_is_not_in_kz(self):
        assert in_kill_zone(_est(5, 0)) is False

    def test_ny_09h_is_in_kz(self):
        assert in_kill_zone(_est(9, 0)) is True

    def test_ny_11h_is_not_in_kz(self):
        assert in_kill_zone(_est(11, 0)) is False

    def test_midnight_is_not_in_kz(self):
        assert in_kill_zone(_est(0, 0)) is False

    def test_14h_is_not_in_kz(self):
        assert in_kill_zone(_est(14, 0)) is False

    def test_london_start_boundary(self):
        assert in_kill_zone(_est(2, 0)) is True

    def test_ny_end_boundary(self):
        assert in_kill_zone(_est(11, 0)) is False


# ---------------------------------------------------------------------------
# next_kill_zone_start
# ---------------------------------------------------------------------------

class TestNextKillZone:
    def test_returns_future_datetime(self):
        mocked_now = _est(12, 0)
        with patch("live.scheduler.now_est", return_value=mocked_now):
            nxt = next_kill_zone_start()
        # La prochaine KZ doit être après l'heure mockée
        assert nxt > mocked_now.astimezone(timezone.utc)

    def test_next_is_london_when_after_ny(self):
        with patch("live.scheduler.now_est", return_value=_est(12, 0)):
            nxt = next_kill_zone_start().astimezone(_EST)
        assert nxt.hour == 2   # London le lendemain

    def test_next_is_ny_when_in_london(self):
        with patch("live.scheduler.now_est", return_value=_est(3, 0)):
            nxt = next_kill_zone_start().astimezone(_EST)
        assert nxt.hour == 8   # NY le même jour


# ---------------------------------------------------------------------------
# run_scheduler
# ---------------------------------------------------------------------------

class TestRunScheduler:
    def test_callback_called_in_kill_zone(self):
        callback = MagicMock()
        with patch("live.scheduler.in_kill_zone", return_value=True), \
             patch("live.scheduler.time.sleep"):
            run_scheduler(callback, max_iterations=3, poll_seconds=0)
        assert callback.call_count == 3

    def test_callback_not_called_outside_kill_zone(self):
        callback = MagicMock()
        with patch("live.scheduler.in_kill_zone", return_value=False), \
             patch("live.scheduler.time.sleep"), \
             patch("live.scheduler.seconds_until_next_kill_zone", return_value=0), \
             patch("live.scheduler.next_kill_zone_start") as mock_nxt:
            mock_nxt.return_value = datetime.now(timezone.utc)
            run_scheduler(callback, max_iterations=2, poll_seconds=0)
        assert callback.call_count == 0

    def test_force_run_now_calls_immediately(self):
        callback = MagicMock()
        with patch("live.scheduler.in_kill_zone", return_value=False), \
             patch("live.scheduler.time.sleep"), \
             patch("live.scheduler.seconds_until_next_kill_zone", return_value=0), \
             patch("live.scheduler.next_kill_zone_start") as mock_nxt:
            mock_nxt.return_value = datetime.now(timezone.utc)
            run_scheduler(callback, max_iterations=1, force_run_now=True)
        assert callback.call_count == 1

    def test_exception_in_callback_does_not_crash_scheduler(self):
        callback = MagicMock(side_effect=RuntimeError("test error"))
        with patch("live.scheduler.in_kill_zone", return_value=True), \
             patch("live.scheduler.time.sleep"):
            run_scheduler(callback, max_iterations=2, poll_seconds=0)
        assert callback.call_count == 2
