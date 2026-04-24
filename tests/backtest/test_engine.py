"""
Tests pour src/backtest/engine.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestConfig, BacktestResult, Trade, run_backtest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ohlcv(
    n: int = 60,
    trend: str = "up",
    base: float = 1.10,
) -> pd.DataFrame:
    """
    Série OHLCV synthétique suffisamment longue pour déclencher la pipeline
    (sessions Kill Zone, swings, FVG, OB, signaux).

    On génère une série 15-min couvrant London + NY (02h-11h EST = 07h-16h UTC).
    """
    # Démarrer à 08:00 UTC (= 03:00 EST = milieu de la Kill Zone London)
    idx = pd.date_range("2024-01-08 08:00", periods=n, freq="15min", tz="UTC")

    rng = np.random.default_rng(42)
    step = 0.001 if trend == "up" else -0.001
    price = base + np.arange(n) * step + rng.normal(0, 0.0005, n)

    highs  = price + np.abs(rng.normal(0, 0.0015, n))
    lows   = price - np.abs(rng.normal(0, 0.0015, n))
    opens  = np.roll(price, 1); opens[0] = price[0]
    closes = price

    # Garantir OHLC cohérent
    highs  = np.maximum(highs, np.maximum(opens, closes))
    lows   = np.minimum(lows,  np.minimum(opens, closes))

    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows,
        "Close": closes, "Volume": [1.0] * n,
    }, index=idx)


def _permissive_config() -> BacktestConfig:
    """Config très permissive pour forcer des signaux dans les tests."""
    return BacktestConfig(
        initial_balance=10_000.0,
        max_concurrent=3,
        structure_lookback=2,
        min_confluence_score=1,
        require_kill_zone=False,
        require_amd_phase3=False,
        confluence_lookback=3,
        risk_pct=0.01,
        rr_ratio=2.0,
    )


# ---------------------------------------------------------------------------
# Schema de sortie
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_returns_backtest_result(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        assert isinstance(res, BacktestResult)

    def test_equity_curve_length(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        assert len(res.equity_curve) == len(df)

    def test_equity_curve_indexed_like_df(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        pd.testing.assert_index_equal(res.equity_curve.index, df.index)

    def test_trades_is_list(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        assert isinstance(res.trades, list)

    def test_all_trades_are_trade_objects(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        assert all(isinstance(t, Trade) for t in res.trades)

    def test_enriched_df_has_pipeline_columns(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        for col in ("bos_bull", "bos_bear", "ob_bull", "fvg_bull", "session"):
            assert col in res.enriched_df.columns, f"Colonne manquante: {col}"


# ---------------------------------------------------------------------------
# Trade properties
# ---------------------------------------------------------------------------

class TestTradeProperties:
    def test_entry_bar_after_signal_bar(self):
        df  = _ohlcv(80)
        res = run_backtest(df, _permissive_config())
        for t in res.trades:
            assert t.entry_bar > t.signal_bar, (
                f"entry_bar={t.entry_bar} doit être > signal_bar={t.signal_bar}"
            )

    def test_exit_bar_gte_entry_bar(self):
        df  = _ohlcv(80)
        res = run_backtest(df, _permissive_config())
        for t in res.trades:
            assert t.exit_bar is not None
            assert t.exit_bar >= t.entry_bar

    def test_exit_reason_valid(self):
        df  = _ohlcv(80)
        res = run_backtest(df, _permissive_config())
        for t in res.trades:
            assert t.exit_reason in ("tp", "sl", "end")

    def test_pnl_not_none_for_closed_trades(self):
        df  = _ohlcv(80)
        res = run_backtest(df, _permissive_config())
        for t in res.trades:
            assert t.pnl is not None

    def test_long_sl_below_entry(self):
        df  = _ohlcv(80)
        res = run_backtest(df, _permissive_config())
        for t in res.trades:
            if t.direction == "long":
                assert t.stop_loss < t.entry_price

    def test_short_sl_above_entry(self):
        df  = _ohlcv(80, trend="down")
        res = run_backtest(df, _permissive_config())
        for t in res.trades:
            if t.direction == "short":
                assert t.stop_loss > t.entry_price


# ---------------------------------------------------------------------------
# Contrainte max_concurrent
# ---------------------------------------------------------------------------

class TestMaxConcurrent:
    def test_max_concurrent_respected(self):
        """À chaque barre, le nombre de trades ouverts ne dépasse pas la limite."""
        df  = _ohlcv(120)
        cfg = _permissive_config()
        cfg.max_concurrent = 1

        res = run_backtest(df, cfg)

        # Reconstruire la timeline des trades ouverts par barre.
        # On exclut la barre de sortie : un trade fermé à la barre i ne compte
        # plus comme ouvert quand de nouveaux trades sont ouverts cette même barre.
        n = len(df)
        open_counts = np.zeros(n, dtype=int)
        for t in res.trades:
            end = t.exit_bar if t.exit_bar is not None else n
            open_counts[t.entry_bar: end] += 1

        assert open_counts.max() <= 1, f"Max concurrent dépassé: {open_counts.max()}"


# ---------------------------------------------------------------------------
# Balance et equity
# ---------------------------------------------------------------------------

class TestEquity:
    def test_equity_starts_at_initial_balance(self):
        df  = _ohlcv(60)
        cfg = _permissive_config()
        res = run_backtest(df, cfg)
        # Avant tout trade, l'equity vaut le capital initial
        assert res.equity_curve.iloc[0] == pytest.approx(cfg.initial_balance, rel=0.01)

    def test_final_balance_property(self):
        df  = _ohlcv(60)
        res = run_backtest(df, _permissive_config())
        assert res.final_balance == pytest.approx(float(res.equity_curve.iloc[-1]))

    def test_equity_always_positive(self):
        """Avec risk_pct=1%, le capital ne doit pas devenir négatif."""
        df  = _ohlcv(200, trend="down")
        res = run_backtest(df, _permissive_config())
        assert res.equity_curve.min() > 0


# ---------------------------------------------------------------------------
# Trade dataclass properties
# ---------------------------------------------------------------------------

class TestTradeDataclass:
    def _make_trade(self, direction="long", exit_reason="tp") -> Trade:
        tp = 1.12 if direction == "long" else 1.08
        sl = 1.08 if direction == "long" else 1.12
        ep = 1.10
        exit_price = tp if exit_reason == "tp" else sl
        return Trade(
            direction=direction,
            entry_bar=1,
            entry_price=ep,
            stop_loss=sl,
            take_profit=tp,
            size_units=10_000.0,
            signal_bar=0,
            exit_bar=5,
            exit_price=exit_price,
            exit_reason=exit_reason,
        )

    def test_long_tp_gives_positive_pnl(self):
        t = self._make_trade("long", "tp")
        assert t.pnl > 0

    def test_long_sl_gives_negative_pnl(self):
        t = self._make_trade("long", "sl")
        assert t.pnl < 0

    def test_short_tp_gives_positive_pnl(self):
        t = self._make_trade("short", "tp")
        assert t.pnl > 0

    def test_short_sl_gives_negative_pnl(self):
        t = self._make_trade("short", "sl")
        assert t.pnl < 0

    def test_pnl_r_equals_rr_for_tp(self):
        """TP à 2× le risque → pnl_r ≈ 2.0."""
        t = Trade(
            direction="long", entry_bar=1, entry_price=1.10,
            stop_loss=1.08, take_profit=1.14,   # risque=0.02, reward=0.04 → 2R
            size_units=1.0, signal_bar=0,
            exit_bar=5, exit_price=1.14, exit_reason="tp",
        )
        assert t.pnl_r == pytest.approx(2.0)

    def test_is_winner_true_for_tp(self):
        assert self._make_trade("long", "tp").is_winner is True

    def test_is_winner_false_for_sl(self):
        assert self._make_trade("long", "sl").is_winner is False

    def test_duration_bars(self):
        t = self._make_trade()
        assert t.duration_bars == 4   # exit_bar(5) - entry_bar(1)
