# Skill: backtest-analysis

Run a full backtest analysis on the current strategy and produce a structured report.

## Steps

1. **Load results**: Read the latest backtest output from `backtests/results/` (JSON or CSV)
2. **Compute metrics** using the quant-analyst standards:
   - Total trades, win rate, average R:R
   - Profit factor, Sharpe ratio, Sortino ratio
   - Max drawdown (absolute and % of account)
   - Monthly and quarterly P&L breakdown
3. **Segment performance**:
   - By pair (EUR/USD vs GBP/USD vs USD/JPY)
   - By session (London Kill Zone vs NY Kill Zone)
   - By confluence score (1–5)
   - By market regime (trending vs ranging, if tagged)
4. **Generate report**: Output a structured markdown report to `backtests/reports/YYYY-MM-DD_report.md`
5. **Flag issues**: If any metric is below threshold (see quant-analyst.md), list them explicitly as "REQUIRES ATTENTION"

## Output format

```
# Backtest Report — [date]

## Summary
[3-line summary of overall performance]

## Core Metrics
[table]

## Segmented Performance  
[tables by pair / session / confluence]

## Issues Flagged
[list or "None"]

## Recommendation
[Approve for OOS / Needs parameter adjustment / Do not proceed]
```
