# Capital-market investment simulation v0.2

[English](README.en-US.md) | [简体中文](README.md)

Two investment agents operate with the same starting capital and tool permissions. The scenario combines real-market research tooling with a simulated ledger and ranks agents by terminal portfolio value after a one-hour wall-clock window.

## Model

- **No map:** this is an information → harness → ledger scenario, not spatial movement.
- **Actions:** `buy_asset`, `sell_asset`, and `wait_and_review`; the instrument is supplied in `parameters.asset_id`.
- **Objects:** `portfolio_book` is the authoritative ledger; `risk_dashboard` is the risk anchor.
- **Capability:** the runtime does not pre-load market facts; agents discover MCP, skills and code execution during the loop.
- **Settlement:** `evaluation/plugin.py` maintains the portfolio ledger; the OS schedules and records provenance.

## Time and completion

- One tick is approximately 60 real seconds; see `world/clock.yaml`.
- Main completion condition: 3,600 wall-clock seconds; safety cap: `tick_limit: 120`.
- Liquidation threshold: terminal portfolio value below 700.

The canonical scenario declarations remain Chinese in this release. IDs, structured values and settlement behavior are language-neutral; this guide is the English orientation layer. The scenario is for simulation and model evaluation only, not investment advice.
