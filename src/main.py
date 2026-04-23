"""
Entry point — paper / live trading mode.

Usage:
    python src/main.py --config config/default.yaml --mode paper
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
logger = logging.getLogger("main")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ICT/SMC Forex trading bot")
    parser.add_argument("--config", default="config/default.yaml", help="Path to YAML config")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    pairs = cfg["pairs"]
    logger.info("Starting in %s mode | pairs: %s", args.mode.upper(), pairs)

    # Phase 5 will wire the live execution loop here.
    # For now, verify the data layer is reachable.
    from data.fetcher import fetch_ohlcv

    for pair in pairs[:1]:  # smoke-test first pair only on startup
        try:
            df = fetch_ohlcv(pair, cfg["timeframes"]["ltf"])
            logger.info("Data layer OK — %s: %d candles loaded", pair, len(df))
        except Exception as exc:
            logger.error("Data layer error for %s: %s", pair, exc)
            sys.exit(1)

    logger.info("Bot initialised. Strategy engine not yet connected (Phase 3).")


if __name__ == "__main__":
    main()
