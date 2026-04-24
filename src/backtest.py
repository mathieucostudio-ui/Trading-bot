"""
Entry point — backtesting mode.

Usage:
    python src/backtest.py --pair EURUSD --start 2020-01-01 --end 2024-12-31
    python src/backtest.py --pairs EURUSD,GBPUSD,USDJPY --start 2020-01-01 --end 2024-12-31
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
    parser.add_argument("--end", help="End date YYYY-MM-DD")
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

    logger.info("Backtest | pairs=%s | %s → %s", pairs, start, end)

    # Phase 4 will wire the full backtest engine here.
    # For now, verify multi-timeframe data loads cleanly for each pair.
    from data.fetcher import fetch_ohlcv
    from data.timeframes import build_mtf

    tfs = [cfg["timeframes"]["ltf"], cfg["timeframes"]["mtf"], cfg["timeframes"]["htf"]]

    for pair in pairs:
        try:
            base = fetch_ohlcv(pair, cfg["timeframes"]["ltf"], start=start, end=end)
            mtf = build_mtf(base, tfs)
            for tf, df in mtf.items():
                logger.info(
                    "  %s %s → %d candles  (%s → %s)",
                    pair, tf, len(df),
                    df.index[0].date(), df.index[-1].date(),
                )
        except Exception as exc:
            logger.error("Failed to load data for %s: %s", pair, exc)
            sys.exit(1)

    from backtest.engine  import BacktestConfig, run_backtest
    from backtest.metrics import compute_metrics
    from backtest.walkforward import walk_forward

    bt_cfg = BacktestConfig(
        initial_balance=bt_cfg.get("initial_balance", 10_000.0),
        max_concurrent=cfg["risk"].get("max_concurrent_trades", 3),
        structure_lookback=cfg["detectors"].get("swing_lookback", 5),
        fvg_body_ratio=cfg["detectors"].get("fvg_body_ratio", 0.5),
        min_confluence_score=bt_cfg.get("min_confluence_score", 3),
        require_kill_zone=bt_cfg.get("require_kill_zone", True),
        require_amd_phase3=bt_cfg.get("require_amd_phase3", True),
        risk_pct=cfg["risk"].get("max_risk_pct", 0.01),
        rr_ratio=cfg["risk"].get("min_rr_ratio", 2.0),
    )

    wf_months_is  = bt_cfg.__dict__.get("wf_is_months",  6)
    wf_months_oos = bt_cfg.__dict__.get("wf_oos_months", 2)

    for pair in pairs:
        logger.info("=" * 60)
        logger.info("Backtesting %s  %s → %s", pair, start, end)
        try:
            base = fetch_ohlcv(pair, cfg["timeframes"]["ltf"], start=start, end=end)
        except Exception as exc:
            logger.error("Chargement des données échoué pour %s: %s", pair, exc)
            sys.exit(1)

        logger.info("  %d barres chargées (%s → %s)",
                    len(base), base.index[0].date(), base.index[-1].date())

        wf_result = walk_forward(base, is_months=wf_months_is,
                                 oos_months=wf_months_oos, config=bt_cfg)

        if wf_result.windows:
            logger.info(wf_result.summary())
        else:
            # Série trop courte pour le walk-forward → backtest simple
            result  = run_backtest(base, bt_cfg)
            metrics = compute_metrics(result.trades,
                                      initial_balance=bt_cfg.initial_balance,
                                      equity_curve=result.equity_curve)
            logger.info("\n%s", metrics)


if __name__ == "__main__":
    main()
