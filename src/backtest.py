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

    logger.info("Data pipeline verified. Strategy engine not yet connected (Phase 3).")


if __name__ == "__main__":
    main()
