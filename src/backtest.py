"""
Entry point — backtesting mode.

Usage:
    python src/backtest.py --pair EURUSD --start 2024-06-01
    python src/backtest.py --pair EURUSD --ltf 1h --start 2024-06-01
    python src/backtest.py --pairs EURUSD,GBPUSD,USDJPY --ltf 1h --start 2024-06-01

Note sur yfinance :
    15m : 60 derniers jours max    →  utilise --ltf 15m avec --start récent
    1h  : 730 derniers jours max   →  recommandé pour backtest plus long
    1d  : historique complet       →  pour une vue long terme
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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
    parser = argparse.ArgumentParser(description="ICT/SMC backtest runner")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--pair", help="Single pair, e.g. EURUSD")
    parser.add_argument("--pairs", help="Comma-separated pairs, e.g. EURUSD,GBPUSD,USDJPY")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end",   help="End date YYYY-MM-DD (défaut: aujourd'hui)")
    parser.add_argument("--ltf",   help="Override timeframe LTF ex: 15m, 1h, 1d (défaut: config)")
    parser.add_argument("--is-months",  type=int, default=6,  help="Fenêtre IS walk-forward (mois)")
    parser.add_argument("--oos-months", type=int, default=2,  help="Fenêtre OOS walk-forward (mois)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    bt_cfg = cfg.get("backtest", {})

    if args.pairs:
        pairs = [p.strip().upper() for p in args.pairs.split(",")]
    elif args.pair:
        pairs = [args.pair.upper()]
    else:
        pairs = cfg["pairs"]

    start = args.start or bt_cfg.get("default_start")
    end = args.end or bt_cfg.get("default_end")

    ltf = args.ltf or cfg["timeframes"]["ltf"]
    logger.info("Backtest | pairs=%s | ltf=%s | %s → %s", pairs, ltf, start, end)

    from data.fetcher import fetch_ohlcv
    from backtest.engine   import BacktestConfig, run_backtest
    from backtest.metrics  import compute_metrics
    from backtest.walkforward import walk_forward

    yaml_bt  = cfg.get("backtest", {})
    engine_cfg = BacktestConfig(
        initial_balance=yaml_bt.get("initial_capital", 10_000.0),
        max_concurrent=cfg["risk"].get("max_concurrent_trades", 3),
        structure_lookback=cfg["detectors"].get("swing_lookback", 5),
        fvg_body_ratio=cfg["detectors"].get("fvg_body_ratio", 0.5),
        min_confluence_score=cfg["detectors"].get("min_confluence_score", 3),
        require_kill_zone=yaml_bt.get("require_kill_zone", True),
        require_amd_phase3=yaml_bt.get("require_amd_phase3", True),
        risk_pct=cfg["risk"].get("max_risk_pct", 0.01),
        rr_ratio=cfg["risk"].get("min_rr_ratio", 2.0),
    )

    for pair in pairs:
        logger.info("=" * 60)
        logger.info("Backtesting %s  %s → %s  [%s]", pair, start, end, ltf)
        try:
            base = fetch_ohlcv(pair, ltf, start=start, end=end)
        except Exception as exc:
            logger.error("Chargement des données échoué pour %s: %s", pair, exc)
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
