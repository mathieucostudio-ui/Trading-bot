"""
Entry point — paper / live trading mode.

Usage:
    python src/main.py                          # paper trading, config par défaut
    python src/main.py --mode paper             # paper trading explicite
    python src/main.py --pairs EURUSD,GBPUSD    # override paires
    python src/main.py --ltf 15m --balance 5000 # override timeframe et capital
    python src/main.py --run-once               # un seul cycle (test/debug)
"""

from __future__ import annotations

import argparse
import logging
import sys

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ICT/SMC Forex paper trader")
    parser.add_argument("--config",   default="config/default.yaml")
    parser.add_argument("--mode",     choices=["paper"], default="paper",
                        help="Mode d'exécution (seul 'paper' disponible en Phase 5)")
    parser.add_argument("--pairs",    help="Override paires ex: EURUSD,GBPUSD")
    parser.add_argument("--ltf",      help="Override timeframe ex: 15m, 1h")
    parser.add_argument("--balance",  type=float, default=None, help="Capital initial USD")
    parser.add_argument("--min-score",type=int,   default=None, help="Override score min (défaut: config)")
    parser.add_argument("--run-once", action="store_true",
                        help="Exécuter un seul cycle puis quitter (test/debug)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    pairs = (
        [p.strip().upper() for p in args.pairs.split(",")]
        if args.pairs else cfg["pairs"]
    )
    ltf        = args.ltf     or cfg["timeframes"]["ltf"]
    balance    = args.balance or cfg["backtest"].get("initial_capital", 10_000.0)
    min_score  = args.min_score or cfg["detectors"].get("min_confluence_score", 4)

    logger.info(
        "Démarrage %s | paires=%s | ltf=%s | balance=%.0f | score>=%d",
        args.mode.upper(), pairs, ltf, balance, min_score,
    )

    from live.trader    import LiveTrader
    from live.scheduler import run_scheduler

    trader = LiveTrader(
        pairs=pairs,
        timeframe=ltf,
        lookback_bars=300,
        min_confluence_score=min_score,
        require_kill_zone=True,
        require_amd_phase3=True,
        structure_lookback=cfg["detectors"].get("swing_lookback", 5),
        fvg_body_ratio=cfg["detectors"].get("fvg_body_ratio", 0.5),
        initial_balance=balance,
        max_concurrent=cfg["risk"].get("max_concurrent_trades", 3),
        risk_pct=cfg["risk"].get("max_risk_pct", 0.01),
        rr_ratio=cfg["risk"].get("min_rr_ratio", 2.0),
    )

    if args.run_once:
        logger.info("Mode --run-once : un seul cycle puis arrêt")
        trader.run_cycle()
        trader.print_summary()
        return

    try:
        run_scheduler(
            callback=trader.run_cycle,
            poll_seconds=60,
        )
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur (Ctrl+C)")
        trader.print_summary()


if __name__ == "__main__":
    main()
