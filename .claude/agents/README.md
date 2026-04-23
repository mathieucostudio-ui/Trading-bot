# Agents

Each agent has a focused role in the strategy development lifecycle. They share the same codebase context but reason from different perspectives.

## Usage

Agents are invoked automatically by Claude Code when the task matches their description, or explicitly via the Agent tool.

## Roles summary

- **strategy-architect** — call when designing new modules, refactoring core logic, or choosing between architectural approaches
- **quant-analyst** — call when interpreting backtest results, computing metrics, or evaluating signal edge
- **risk-auditor** — call before any live deployment; reviews SL/TP logic, position sizing, and max exposure
- **devils-advocate** — call to challenge a strategy before committing to it; finds edge cases and overfitting
- **trading-historian** — call when researching how a specific market condition behaved historically
