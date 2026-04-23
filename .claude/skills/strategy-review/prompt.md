# Skill: strategy-review

Perform a full code and logic review of a strategy module.

## Steps

1. **Identify the module**: The file or directory to review (passed as argument, or the most recently modified strategy file)
2. **Logic review**:
   - Verify ICT/SMC concept implementation matches the spec in `.claude/agents/strategy-architect.md`
   - Check for look-ahead bias (using future data in signal calculation)
   - Verify swing point detection uses only `i-N` to `i` data, never `i+N`
   - Confirm FVG detection: `low[i+1] > high[i-1]` uses confirmed closed candles only
   - Confirm OB detection: displacement candle must be fully closed before OB is valid
3. **Code review**:
   - No magic numbers — all thresholds in config YAML
   - Vectorized operations (no row-by-row Python loops on DataFrames)
   - Each function has a clear single responsibility
   - Edge cases handled: empty DataFrame, < 3 candles, NaN values
4. **Risk review** (delegate to risk-auditor agent):
   - SL/TP placement logic
   - Position sizing formula
5. **Output**: Structured review with PASS / WARN / FAIL per section

## Output format

```
# Strategy Review — [module name]

## Look-ahead bias: PASS/FAIL
## Signal logic: PASS/WARN/FAIL  
## Code quality: PASS/WARN/FAIL
## Risk management: PASS/WARN/FAIL

## Issues (blocking)
## Warnings (non-blocking)
## Approved for backtest: YES/NO
```
