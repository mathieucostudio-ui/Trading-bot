# Skill: trading-changelog

Generate a structured changelog from recent git commits, formatted for trading strategy versioning.

## Steps

1. **Get recent commits**: `git log --oneline -30` from the current branch
2. **Categorize each commit**:
   - `strategy`: changes to signal logic, entry/exit rules, ICT/SMC detectors
   - `risk`: changes to SL/TP, position sizing, exposure limits
   - `data`: changes to data fetching, timeframe handling, pair configuration
   - `backtest`: changes to backtesting framework or scripts
   - `infra`: project structure, dependencies, config
   - `fix`: bug fixes
3. **Format changelog**:

```markdown
## [version] — YYYY-MM-DD

### Strategy changes
- [what changed and why it was changed]

### Risk management
- [what changed]

### Data & infrastructure
- [what changed]

### Bug fixes
- [what was fixed]

### Backtest results delta
- [if available: key metric before → after]
```

4. **Append** to `CHANGELOG.md` at the project root (create if absent)
5. **Suggest next version number** based on semantic versioning:
   - Major bump: strategy logic fundamentally changed
   - Minor bump: new feature or new pair added
   - Patch bump: bug fix or parameter tweak
