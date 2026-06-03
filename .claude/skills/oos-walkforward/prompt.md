# Skill: oos-walkforward

Run an out-of-sample (OOS) walk-forward validation to test strategy robustness against unseen data.

## What this tests

Walk-forward validation splits historical data into rolling windows:
- **In-sample (IS)**: optimize parameters → find best config
- **Out-of-sample (OOS)**: test that config on the next unseen period → measure real edge

If IS performance >> OOS performance consistently, the strategy is overfitted.

## Steps

1. **Define windows**:
   - IS window: 6 months
   - OOS window: 2 months
   - Step: 1 month (rolling)
   - Minimum windows: 6 (covers 1 full year of OOS data)

2. **For each window**:
   - Run backtest on IS period with parameter grid
   - Select best parameter set (by Sharpe ratio, not profit factor — less prone to outliers)
   - Run backtest on OOS period with those parameters
   - Record: IS Sharpe, OOS Sharpe, IS profit factor, OOS profit factor

3. **Compute robustness score**:
   - OOS efficiency = OOS Sharpe / IS Sharpe
   - Target: OOS efficiency > 0.6 (i.e., OOS retains at least 60% of IS performance)
   - Below 0.4: overfitted, do not deploy

4. **Generate walk-forward report** to `backtests/reports/walkforward_YYYY-MM-DD.md`:
   - Window-by-window IS vs OOS table
   - OOS efficiency ratio
   - Parameter stability (did optimal params vary wildly between windows?)
   - Final verdict: ROBUST / MARGINAL / OVERFITTED

## Pairs to test

Run separately for EUR/USD, GBP/USD, USD/JPY. A strategy must pass on at least 2 of 3 pairs to be considered robust.
