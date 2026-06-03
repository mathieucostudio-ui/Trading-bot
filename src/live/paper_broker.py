"""
Paper Broker — simulation d'exécution en temps réel sans argent réel.

Gère les positions ouvertes, vérifie SL/TP sur chaque nouvelle barre,
et journalise chaque trade dans logs/paper_trades.jsonl.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from strategy.signal import TradeSignal
from risk.manager import SizedSignal

logger = logging.getLogger(__name__)

LOGS_DIR = Path("logs")
TRADE_LOG = LOGS_DIR / "paper_trades.jsonl"


# ---------------------------------------------------------------------------
# Position ouverte
# ---------------------------------------------------------------------------

@dataclass
class PaperPosition:
    id: str
    pair: str
    direction: str          # 'long' | 'short'
    entry_price: float
    stop_loss: float
    take_profit: float
    size_units: float
    entry_time: str         # ISO UTC
    confluence_score: int
    exit_price: Optional[float] = None
    exit_time: Optional[str]   = None
    exit_reason: Optional[str] = None   # 'tp' | 'sl' | 'manual'
    pnl: Optional[float]       = None

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def close(self, price: float, time: str, reason: str) -> None:
        self.exit_price  = price
        self.exit_time   = time
        self.exit_reason = reason
        mult = 1.0 if self.direction == "long" else -1.0
        self.pnl = mult * (price - self.entry_price) * self.size_units


# ---------------------------------------------------------------------------
# Paper Broker
# ---------------------------------------------------------------------------

class PaperBroker:
    """
    Exécute des ordres sur papier et vérifie SL/TP à chaque barre.
    Journalise chaque trade fermé dans logs/paper_trades.jsonl.
    """

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        max_concurrent: int = 3,
    ) -> None:
        self.balance         = initial_balance
        self.initial_balance = initial_balance
        self.max_concurrent  = max_concurrent
        self.positions: list[PaperPosition] = []
        self._trade_counter  = 0
        LOGS_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Propriétés de synthèse
    # ------------------------------------------------------------------

    @property
    def open_positions(self) -> list[PaperPosition]:
        return [p for p in self.positions if p.is_open]

    @property
    def closed_positions(self) -> list[PaperPosition]:
        return [p for p in self.positions if not p.is_open]

    @property
    def equity(self) -> float:
        unrealised = sum(
            (p.entry_price - self.balance) for p in self.open_positions
        )
        return self.balance

    @property
    def total_pnl(self) -> float:
        return sum(p.pnl for p in self.closed_positions if p.pnl is not None)

    # ------------------------------------------------------------------
    # Ouverture d'une position
    # ------------------------------------------------------------------

    def open_position(self, signal: SizedSignal, pair: str) -> Optional[PaperPosition]:
        if len(self.open_positions) >= self.max_concurrent:
            logger.info("[%s] Max concurrent atteint — signal ignoré", pair)
            return None

        # Un seul trade par paire à la fois
        if any(p.pair == pair for p in self.open_positions):
            logger.info("[%s] Position déjà ouverte — signal ignoré", pair)
            return None

        self._trade_counter += 1
        pos = PaperPosition(
            id=f"PT{self._trade_counter:04d}",
            pair=pair,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            size_units=signal.size_units,
            entry_time=datetime.now(timezone.utc).isoformat(),
            confluence_score=signal.signal.confluence_score,
        )
        self.positions.append(pos)
        logger.info(
            "[%s] OPEN %s  entry=%.5f  sl=%.5f  tp=%.5f  size=%.2f  score=%d",
            pair, pos.direction.upper(), pos.entry_price,
            pos.stop_loss, pos.take_profit, pos.size_units, pos.confluence_score,
        )
        return pos

    # ------------------------------------------------------------------
    # Mise à jour SL/TP sur nouvelle barre
    # ------------------------------------------------------------------

    def update(self, pair: str, high: float, low: float, close: float) -> list[PaperPosition]:
        """
        Appelé à chaque nouvelle barre. Vérifie SL/TP pour les positions
        ouvertes sur cette paire. Retourne les positions fermées lors de cet appel.
        """
        now    = datetime.now(timezone.utc).isoformat()
        closed = []

        for pos in [p for p in self.open_positions if p.pair == pair]:
            exit_price  = None
            exit_reason = None

            if pos.direction == "long":
                if low <= pos.stop_loss:
                    exit_price, exit_reason = pos.stop_loss, "sl"
                elif high >= pos.take_profit:
                    exit_price, exit_reason = pos.take_profit, "tp"
            else:
                if high >= pos.stop_loss:
                    exit_price, exit_reason = pos.stop_loss, "sl"
                elif low <= pos.take_profit:
                    exit_price, exit_reason = pos.take_profit, "tp"

            if exit_price is not None:
                pos.close(exit_price, now, exit_reason)
                self.balance += pos.pnl  # type: ignore[operator]
                self._log_trade(pos)
                closed.append(pos)
                emoji = "✅" if pos.pnl > 0 else "❌"
                logger.info(
                    "[%s] CLOSE %s %s  exit=%.5f  pnl=%+.2f USD  balance=%.2f",
                    pair, pos.id, emoji, exit_price, pos.pnl, self.balance,
                )

        return closed

    # ------------------------------------------------------------------
    # Journalisation
    # ------------------------------------------------------------------

    def _log_trade(self, pos: PaperPosition) -> None:
        with open(TRADE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(pos)) + "\n")

    def print_summary(self) -> None:
        closed = self.closed_positions
        if not closed:
            logger.info("Aucun trade fermé pour l'instant.")
            return
        winners = [p for p in closed if p.pnl and p.pnl > 0]
        wr = len(winners) / len(closed) * 100
        total_pnl = sum(p.pnl for p in closed if p.pnl)
        logger.info(
            "=== RÉSUMÉ PAPER TRADING ===\n"
            "  Trades fermés : %d\n"
            "  Win Rate      : %.1f%%\n"
            "  Total PnL     : %+.2f USD\n"
            "  Balance       : %.2f USD",
            len(closed), wr, total_pnl, self.balance,
        )
