# Investment Agent Benchmark v1

## What it measures

TraceArena evaluates whether an investment agent can turn cited research into a valid simulated order and leave a replayable evidence → decision → order → settlement chain. The deterministic portfolio verifier measures return, excess return, maximum drawdown, turnover, and transaction costs.

The primary metric is:

`risk-adjusted excess return = excess return % - 0.5 × maximum drawdown %`

## Current publication status

The checked-in result is a **contract baseline**, not a model leaderboard. Its two entrants are deterministic scripted controls: an evidence-first buyer and a cash control. It proves that the same fixture produces the same semantic replay and score without an API key, network access, or brokerage connection.

The bundled synthetic fixture still carries `internal_synthetic_pending_approval` provenance and a pending maintainer confirmation for its proposed CC0-1.0 dedication. The report exposes that status rather than presenting it as an approved public financial dataset.

We will label results as model comparisons only when every entry includes model/provider identity, scenario and fixture digests, role rotation, seeds, complete replay artifacts, and verifier output. Community submissions that cannot be independently reproduced remain explicitly unverified.

## Reproduce

Fastest path: [open the pinned Colab notebook](https://colab.research.google.com/github/tonyhyworld/TraceArena/blob/main/examples/investment_benchmark/TraceArena_Investment_Benchmark_v1.ipynb). It clones v0.1.12, runs the no-key benchmark, and verifies the generated report against the published baseline.

```bash
python backend/scripts/investment_benchmark.py \
  --output runs/investment_agent_benchmark_v1
```

Inspect `benchmark_report.json`, `LEADERBOARD.md`, and the replay artifacts under `replay/`. The command rejects a modified replay when its integrity or semantic digest no longer matches the run manifest.

## Evaluation contract

| Layer | Rule |
| --- | --- |
| Research | New positions require a verified quote plus at least two non-quote research results; role-specific evidence rules also apply. |
| Universe | Simulated A-share and Hong Kong instruments only. |
| Execution | Fixed 3 bps commission and 5 bps slippage; insufficient cash, invalid positions, stale evidence, and closed windows are rejected. |
| Ledger | Cash, holdings, fills, mark-to-market value, drawdown, turnover, and costs are maintained by deterministic scenario code. |
| Ranking | Risk-adjusted excess return descending; transaction cost ascending breaks exact score ties. |
| Safety | Synthetic fixture, no network, no brokerage, no financial advice, and no claim about future returns. |

## Limitations and next step

The small two-tick fixture validates mechanics, not investment skill or statistical significance. The next qualified release needs multiple hidden market regimes, more decision windows, role rotation, repeated seeds, and real model-backed agents run under identical data and cost boundaries.

Reference result: [`benchmarks/investment-agent-v1/LEADERBOARD.md`](../../benchmarks/investment-agent-v1/LEADERBOARD.md).
