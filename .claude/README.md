# Claude Configuration — Trading-bot

This directory contains Claude Code configuration for the ICT/SMC Forex trading bot.

## Agents

Specialized agents for different aspects of strategy development. Invoke them via the Agent tool or `@agent-name` syntax.

| Agent | Role |
|---|---|
| `strategy-architect` | Designs strategy components and system architecture |
| `quant-analyst` | Statistical analysis, backtesting metrics, signal quality |
| `risk-auditor` | Risk management review, drawdown, position sizing |
| `devils-advocate` | Challenges assumptions, finds overfitting, stress-tests logic |
| `trading-historian` | Historical market research, regime analysis, precedents |

## Skills

Reusable workflows triggered via `/skill-name`.

| Skill | Purpose |
|---|---|
| `backtest-analysis` | Run and interpret a full backtest report |
| `strategy-review` | Full code + logic review of a strategy module |
| `oos-walkforward` | Out-of-sample walk-forward validation |
| `trading-changelog` | Generate structured changelog from recent commits |
| `version-bump` | Bump version and tag a release |

## Pairs in scope

- EUR/USD · GBP/USD · USD/JPY

## Methodology

ICT (Inner Circle Trader) + SMC (Smart Money Concepts) — multi-timeframe confluence model based on Kill Zones, Liquidity sweeps, Order Blocks, and Fair Value Gaps.
