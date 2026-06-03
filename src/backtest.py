"""
Entry point — backtesting mode.

Usage:
    python src/backtest.py --pair EURUSD --ltf 1h --start 2024-05-01
    python src/backtest.py --pairs EURUSD,GBPUSD,USDJPY --ltf 1h --start 2024-05-01
    python src/backtest.py --pair USDJPY --ltf 1h --start 2024-05-01 --min-score 4
    python src/backtest.py --pair EURUSD --ltf 1h --start 2024-05-01 --no-amd --no-kill-zone

Note sur les limites yfinance :
    15m : 60 derniers jours max
    1h  : 730 derniers jours max  (recommandé)
    1d  : historique complet
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backtest")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="ICT/SMC backtest runner",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--config",  default="config/default.yaml")
    parser.add_argument("--pair",    help="Paire unique, ex: EURUSD")
    parser.add_argument("--pairs",   help="Paires séparées par virgule, ex: EURUSD,GBPUSD,USDJPY")
    parser.add_argument("--start",   help="Date de début YYYY-MM-DD")
    parser.add_argument("--end",     help="Date de fin YYYY-MM-DD (défaut: aujourd'hui)")
    parser.add_argument("--ltf",     help="Timeframe ex: 15m, 1h, 1d (défaut: config)")
    parser.add_argument("--is-months",  type=int, default=6, help="Fenêtre IS walk-forward en mois (défaut: 6)")
    parser.add_argument("--oos-months", type=int, default=2, help="Fenêtre OOS walk-forward en mois (défaut: 2)")
    # Overrides stratégie
    parser.add_argument("--min-score",    type=int, default=None, help="Score de confluence minimum (défaut: config)")
    parser.add_argument("--no-amd",       action="store_true",    help="Désactiver le filtre AMD phase 3")
    parser.add_argument("--no-kill-zone", action="store_true",    help="Désactiver le filtre Kill Zone")
    parser.add_argument("--rr",           type=float, default=None, help="Ratio Risk:Reward (défaut: config)")
    args = parser.parse_args(argv)

    cfg     = load_config(args.config)
    yaml_bt = cfg.get("backtest", {})

    if args.pairs:
        pairs = [p.strip().upper() for p in args.pairs.split(",")]
    elif args.pair:
        pairs = [args.pair.upper()]
    else:
        pairs = cfg["pairs"]

    # Défaut end = aujourd'hui (pas la date fixe du config)
    start = args.start or yaml_bt.get("default_start")
    end   = args.end   # None = yfinance utilise aujourd'hui

    ltf = args.ltf or cfg["timeframes"]["ltf"]

    from data.fetcher import fetch_ohlcv
    from backtest.engine      import BacktestConfig, run_backtest
    from backtest.metrics     import compute_metrics
    from backtest.walkforward import walk_forward

    # Construire la config moteur avec les overrides CLI
    engine_cfg = BacktestConfig(
        initial_balance=yaml_bt.get("initial_capital", 10_000.0),
        max_concurrent=cfg["risk"].get("max_concurrent_trades", 3),
        structure_lookback=cfg["detectors"].get("swing_lookback", 5),
        fvg_body_ratio=cfg["detectors"].get("fvg_body_ratio", 0.5),
        min_confluence_score=args.min_score or cfg["detectors"].get("min_confluence_score", 3),
        require_kill_zone=not args.no_kill_zone,
        require_amd_phase3=not args.no_amd,
        risk_pct=cfg["risk"].get("max_risk_pct", 0.01),
        rr_ratio=args.rr or cfg["risk"].get("min_rr_ratio", 2.0),
    )

    logger.info(
        "Backtest | pairs=%s | ltf=%s | %s → %s | score>=%d | amd=%s | kz=%s | rr=%.1f",
        pairs, ltf, start, end or "aujourd'hui",
        engine_cfg.min_confluence_score,
        not args.no_amd,
        not args.no_kill_zone,
        engine_cfg.rr_ratio,
    )

    for pair in pairs:
        logger.info("=" * 60)
        logger.info("Backtesting %s  [%s]", pair, ltf)
        try:
            base = fetch_ohlcv(pair, ltf, start=start, end=end)
        except Exception as exc:
            logger.error("Chargement échoué pour %s: %s", pair, exc)
            sys.exit(1)

        logger.info("  %d barres chargées (%s → %s)",
                    len(base), base.index[0].date(), base.index[-1].date())

        wf_result = walk_forward(
            base,
            is_months=args.is_months,
            oos_months=args.oos_months,
            config=engine_cfg,
        )

        if wf_result.windows:
            logger.info("\n" + wf_result.summary())
        else:
            logger.info("  Données insuffisantes pour walk-forward → backtest simple")
            result  = run_backtest(base, engine_cfg)
            metrics = compute_metrics(
                result.trades,
                initial_balance=engine_cfg.initial_balance,
                equity_curve=result.equity_curve,
            )
            logger.info("\n%s", metrics)


if __name__ == "__main__":
    main()
