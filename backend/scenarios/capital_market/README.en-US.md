# Capital-market professional evaluation — Public Edition v0.3.0

[English](README.en-US.md) | [简体中文](README.md)

Two investment agents are evaluated under the same capital, data boundaries, and tool permissions. The scenario supports optional market research, always uses a simulated ledger, applies commission and slippage, and reports risk-adjusted excess return.

This is a public professional strategy-evaluation scenario, not an automated trading system. The default path uses mock agents, no-key replay and a simulated portfolio. Users may bring their own model provider and, where legally authorized, enable read-only market research tools. The pack never connects to a brokerage or submits real orders.

## Model

- **No map:** this is an information → harness → ledger scenario, not spatial movement.
- **Actions:** `buy_asset`, `sell_asset`, and `wait_and_review`; the instrument is supplied in `parameters.asset_id`.
- **Objects:** `portfolio_book` is the authoritative ledger; `risk_dashboard` is the risk anchor.
- **Capability:** the runtime does not pre-load market facts; agents discover MCP, skills and code execution during the loop.
- **Settlement:** `evaluation/plugin.py` maintains the portfolio ledger; the OS schedules and records provenance.

## Evaluation window and results

- One tick is approximately 60 real seconds; see `world/clock.yaml`.
- Default window: 3,600 wall-clock seconds; safety cap: `tick_limit: 120`.
- Reported metrics: portfolio return, benchmark excess return, maximum drawdown, turnover, and transaction costs.
- Primary metric: `excess return percentage - 0.5 × maximum drawdown`.

The canonical scenario declarations remain Chinese in this release. IDs, structured values and settlement behavior are language-neutral; this guide is the English orientation layer. For a no-key proof, run `backend/scripts/market_replay.py` with the fixture from the repository quickstart. Use `backend/framework.public.yaml` for the full public frontend; copy `backend/framework.example.yaml` only when configuring your own provider and authorized tools. The scenario is for simulation, agent evaluation and decision-process research only—not investment advice, brokerage execution or a guarantee of returns. Respect each data provider's terms and redistribution limits.
