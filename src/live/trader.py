"""
Trader live/paper — boucle principale de trading en temps réel.

À chaque cycle (appelé par le scheduler) :
  1. Télécharge les dernières barres depuis yfinance
  2. Met à jour les positions ouvertes (SL/TP)
  3. Lance la pipeline de détection ICT
  4. Génère et filtre les signaux
  5. Applique le risk management
  6. Ouvre les nouvelles positions sur le paper broker
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from data.fetcher import fetch_ohlcv
from detectors import run_pipeline
from strategy.signal import generate_signals
from risk.manager import RiskConfig, apply_risk
from live.paper_broker import PaperBroker, PaperPosition

logger = logging.getLogger(__name__)


class LiveTrader:
    """
    Orchestre le cycle complet fetch → detect → signal → risk → order.
    """

    def __init__(
        self,
        pairs: list[str],
        timeframe: str = "15m",
        lookback_bars: int = 300,
        min_confluence_score: int = 4,
        require_kill_zone: bool = True,
        require_amd_phase3: bool = True,
        structure_lookback: int = 5,
        fvg_body_ratio: float = 0.5,
        ob_lookback: int = 10,
        initial_balance: float = 10_000.0,
        max_concurrent: int = 3,
        risk_pct: float = 0.01,
        rr_ratio: float = 2.0,
        sl_buffer_pct: float = 0.001,
    ) -> None:
        self.pairs                 = pairs
        self.timeframe             = timeframe
        self.lookback_bars         = lookback_bars
        self.min_confluence_score  = min_confluence_score
        self.require_kill_zone     = require_kill_zone
        self.require_amd_phase3    = require_amd_phase3
        self.structure_lookback    = structure_lookback
        self.fvg_body_ratio        = fvg_body_ratio
        self.ob_lookback           = ob_lookback

        self.risk_cfg = RiskConfig(
            account_balance=initial_balance,
            risk_pct=risk_pct,
            rr_ratio=rr_ratio,
            sl_buffer_pct=sl_buffer_pct,
            max_concurrent=max_concurrent,
        )

        self.broker = PaperBroker(
            initial_balance=initial_balance,
            max_concurrent=max_concurrent,
        )

    # ------------------------------------------------------------------
    # Cycle principal (appelé par le scheduler)
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """Un cycle complet pour toutes les paires."""
        logger.info("--- Nouveau cycle de trading ---")
        logger.info(
            "Balance: %.2f USD | Positions ouvertes: %d",
            self.broker.balance, len(self.broker.open_positions),
        )

        for pair in self.pairs:
            try:
                self._process_pair(pair)
            except Exception as exc:
                logger.error("[%s] Erreur dans le cycle: %s", pair, exc, exc_info=True)

    # ------------------------------------------------------------------
    # Traitement d'une paire
    # ------------------------------------------------------------------

    def _process_pair(self, pair: str) -> None:
        # 1. Fetch des dernières barres
        df = self._fetch(pair)
        if df is None or len(df) < self.lookback_bars // 2:
            logger.warning("[%s] Données insuffisantes (%d barres)", pair, len(df) if df is not None else 0)
            return

        # 2. Mise à jour SL/TP des positions ouvertes
        last = df.iloc[-1]
        closed = self.broker.update(
            pair=pair,
            high=float(last["High"]),
            low=float(last["Low"]),
            close=float(last["Close"]),
        )

        # 3. Pipeline de détection
        enriched_df, artifacts = run_pipeline(
            df,
            structure_lookback=self.structure_lookback,
            fvg_body_ratio=self.fvg_body_ratio,
            ob_lookback=self.ob_lookback,
        )

        # 4. Signaux sur la dernière barre uniquement
        signals = generate_signals(
            enriched_df,
            min_score=self.min_confluence_score,
            require_kill_zone=self.require_kill_zone,
            require_amd_phase3=self.require_amd_phase3,
        )

        # Garder seulement les signaux sur la dernière barre
        last_bar_idx = len(enriched_df) - 1
        signals = [s for s in signals if s.bar_index == last_bar_idx]

        if not signals:
            logger.debug("[%s] Aucun signal sur la barre courante", pair)
            return

        # 5. Risk management
        sized = apply_risk(signals, enriched_df, artifacts.obs, self.risk_cfg)

        # 6. Ouverture des positions
        for ss in sized:
            pos = self.broker.open_position(ss, pair=pair)
            if pos:
                logger.info(
                    "[%s] Signal %s | score=%d | entry=%.5f | sl=%.5f | tp=%.5f",
                    pair, ss.direction.upper(), ss.signal.confluence_score,
                    ss.entry_price, ss.stop_loss, ss.take_profit,
                )

    # ------------------------------------------------------------------
    # Fetch des données récentes
    # ------------------------------------------------------------------

    def _fetch(self, pair: str) -> Optional[pd.DataFrame]:
        try:
            return fetch_ohlcv(pair, self.timeframe)
        except Exception as exc:
            logger.error("[%s] Erreur de téléchargement: %s", pair, exc)
            return None

    # ------------------------------------------------------------------
    # Résumé
    # ------------------------------------------------------------------

    def print_summary(self) -> None:
        self.broker.print_summary()
