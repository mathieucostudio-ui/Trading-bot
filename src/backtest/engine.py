"""
Backtest engine: simulation bar-à-bar sans biais de look-ahead.

Règles d'exécution :
  - Le signal est généré sur la clôture de la barre i.
  - L'entrée se fait à l'OPEN de la barre i+1 (exécution réaliste).
  - SL/TP sont vérifiés à chaque barre suivante via High/Low.
  - Si SL et TP sont tous deux touchés sur la même barre, le SL est retenu
    (hypothèse conservatrice). Exception : si la barre est haussière (close >
    open) pour un long, on retient le TP (la montée a probablement précédé).
  - Le nombre de trades simultanés est limité par BacktestConfig.max_concurrent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from detectors import run_pipeline, PipelineArtifacts
from strategy.signal import generate_signals, TradeSignal
from risk.manager import RiskConfig, SizedSignal, apply_risk


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    initial_balance: float = 10_000.0
    max_concurrent: int = 3
    # Pipeline
    structure_lookback: int = 5
    fvg_body_ratio: float = 0.5
    liquidity_range_pct: float = 0.001
    ob_lookback: int = 10
    filter_asian_fvg: bool = True
    # Signal
    min_confluence_score: int = 3
    require_kill_zone: bool = True
    require_amd_phase3: bool = True
    confluence_lookback: int = 5
    # Risk
    risk_pct: float = 0.01
    rr_ratio: float = 2.0
    sl_buffer_pct: float = 0.001


# ---------------------------------------------------------------------------
# Trade data class
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    direction: str          # 'long' | 'short'
    entry_bar: int
    entry_price: float
    stop_loss: float
    take_profit: float
    size_units: float
    signal_bar: int         # bar where the signal was detected
    exit_bar: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # 'tp' | 'sl' | 'end'

    @property
    def pnl(self) -> Optional[float]:
        if self.exit_price is None:
            return None
        multiplier = 1.0 if self.direction == "long" else -1.0
        return multiplier * (self.exit_price - self.entry_price) * self.size_units

    @property
    def pnl_r(self) -> Optional[float]:
        """Return in multiples of R (risk)."""
        if self.exit_price is None:
            return None
        risk_per_unit = abs(self.entry_price - self.stop_loss)
        if risk_per_unit == 0:
            return 0.0
        multiplier = 1.0 if self.direction == "long" else -1.0
        return multiplier * (self.exit_price - self.entry_price) / risk_per_unit

    @property
    def is_winner(self) -> Optional[bool]:
        p = self.pnl
        return None if p is None else p > 0

    @property
    def duration_bars(self) -> Optional[int]:
        if self.exit_bar is None:
            return None
        return self.exit_bar - self.entry_bar


# ---------------------------------------------------------------------------
# Backtest result
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series      # length == len(df), indexed by df.index
    config: BacktestConfig
    enriched_df: pd.DataFrame    # pipeline output (for further analysis)

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_reason != "end"]

    @property
    def final_balance(self) -> float:
        if not self.equity_curve.empty:
            return float(self.equity_curve.iloc[-1])
        return self.config.initial_balance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame,
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """
    Run a full ICT/SMC backtest on an OHLCV DataFrame.

    Args:
        df:     Canonical OHLCV DataFrame (UTC index, from fetcher.py).
        config: BacktestConfig; uses defaults if None.

    Returns:
        BacktestResult with all trades and equity curve.
    """
    if config is None:
        config = BacktestConfig()

    risk_cfg = RiskConfig(
        account_balance=config.initial_balance,
        risk_pct=config.risk_pct,
        rr_ratio=config.rr_ratio,
        sl_buffer_pct=config.sl_buffer_pct,
        max_concurrent=config.max_concurrent,
    )

    # --- 1. Run detection pipeline ---
    enriched_df, artifacts = run_pipeline(
        df,
        structure_lookback=config.structure_lookback,
        fvg_body_ratio=config.fvg_body_ratio,
        liquidity_range_pct=config.liquidity_range_pct,
        ob_lookback=config.ob_lookback,
        filter_asian_fvg=config.filter_asian_fvg,
    )

    # --- 2. Generate signals ---
    signals = generate_signals(
        enriched_df,
        min_score=config.min_confluence_score,
        require_kill_zone=config.require_kill_zone,
        require_amd_phase3=config.require_amd_phase3,
        confluence_lookback=config.confluence_lookback,
    )

    # --- 3. Attach SL / TP / size ---
    sized = apply_risk(signals, enriched_df, artifacts.obs, risk_cfg)

    # --- 4. Simulate execution ---
    trades, equity = _simulate(df, enriched_df, sized, config)

    return BacktestResult(
        trades=trades,
        equity_curve=equity,
        config=config,
        enriched_df=enriched_df,
    )


# ---------------------------------------------------------------------------
# Simulation loop
# ---------------------------------------------------------------------------

def _simulate(
    df: pd.DataFrame,
    enriched_df: pd.DataFrame,
    sized_signals: list[SizedSignal],
    config: BacktestConfig,
) -> tuple[list[Trade], pd.Series]:
    n = len(df)
    opens  = df["Open"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values

    balance = config.initial_balance
    equity  = np.full(n, config.initial_balance, dtype=float)

    # Index signals by the bar they should be ENTERED (signal_bar + 1)
    pending: dict[int, list[SizedSignal]] = {}
    for ss in sized_signals:
        entry_bar = ss.signal.bar_index + 1
        if entry_bar < n:
            pending.setdefault(entry_bar, []).append(ss)

    open_trades: list[Trade] = []
    all_trades:  list[Trade] = []

    for i in range(n):
        # --- Check SL / TP on open trades ---
        still_open: list[Trade] = []
        for t in open_trades:
            closed, t = _check_exit(t, i, highs[i], lows[i], closes[i], opens[i])
            if closed:
                balance += t.pnl  # type: ignore[operator]
                all_trades.append(t)
            else:
                still_open.append(t)
        open_trades = still_open

        # --- Open new trades from pending signals ---
        if i in pending:
            for ss in pending[i]:
                if len(open_trades) >= config.max_concurrent:
                    break
                t = Trade(
                    direction=ss.signal.direction,
                    entry_bar=i,
                    entry_price=float(opens[i]),   # enter at bar's open
                    stop_loss=ss.stop_loss,
                    take_profit=ss.take_profit,
                    size_units=ss.size_units,
                    signal_bar=ss.signal.bar_index,
                )
                open_trades.append(t)

        equity[i] = balance

    # Close remaining at end of data
    for t in open_trades:
        t.exit_bar    = n - 1
        t.exit_price  = float(closes[-1])
        t.exit_reason = "end"
        balance += t.pnl  # type: ignore[operator]
        all_trades.append(t)

    return all_trades, pd.Series(equity, index=df.index, name="equity")


def _check_exit(
    trade: Trade,
    bar: int,
    high: float,
    low: float,
    close: float,
    open_: float,
) -> tuple[bool, Trade]:
    """
    Return (closed, trade). Uses bar direction as heuristic when both
    SL and TP are touched on the same bar.
    """
    sl_hit = tp_hit = False

    if trade.direction == "long":
        sl_hit = low  <= trade.stop_loss
        tp_hit = high >= trade.take_profit
    else:
        sl_hit = high >= trade.stop_loss
        tp_hit = low  <= trade.take_profit

    if not sl_hit and not tp_hit:
        return False, trade

    if sl_hit and tp_hit:
        # Both hit: use bar direction as heuristic
        bull_bar = close >= open_
        if (trade.direction == "long" and bull_bar) or (trade.direction == "short" and not bull_bar):
            sl_hit = False   # TP hit first
        else:
            tp_hit = False   # SL hit first

    if tp_hit:
        trade.exit_bar    = bar
        trade.exit_price  = trade.take_profit
        trade.exit_reason = "tp"
    else:
        trade.exit_bar    = bar
        trade.exit_price  = trade.stop_loss
        trade.exit_reason = "sl"

    return True, trade
