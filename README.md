# AegisQuant

> Evidence-first agentic investment research, honest backtesting, deterministic risk, and governed self-improvement.

AegisQuant is a capability-rich modular monolith for **investment research, backtesting, and simulated paper execution only**. Agents may investigate, interpret, challenge, and propose. Typed deterministic components validate evidence, calculate forecasts, construct portfolios, enforce risk, simulate fills, reconcile the ledger, and govern promotion.

## Safety boundary

- No live-broker implementation or entry point.
- Models cannot size positions, modify risk, or place orders.
- Replay and historical modes reject network-capable providers.
- Historical evidence must satisfy `available_at <= as_of`.
- Data-integrity failures halt; model failures abstain.
- Candidate improvements cannot self-promote.

This is research software, not investment advice.

## Quick start

Requires Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check aegis apps tests
uv run mypy aegis apps
```

### No-key deterministic replay

```bash
uv run aegis replay data/fixtures/cases/nvda_earnings_case.json
```

The command reads only checked-in local Parquet/JSON fixtures, produces a canonical cycle receipt, and appends an idempotent record to `run_data/aegisquant.sqlite`.

### Historical backtest through the same cycle

```bash
uv run aegis backtest \
  --fund configs/funds/demo-fund.yaml \
  --tickers AAPL,MSFT,NVDA,AMZN,GOOGL \
  --start 2024-01-01 \
  --end 2024-12-31
```

Replay and backtest share `aegis.fund.run_cycle.run_cycle`, deterministic portfolio construction, the hard risk gate, and `SimBroker`.

## Implemented deterministic spine

- strict Pydantic v2 case, evidence, forecast, source, memory, claim, portfolio, risk, execution, and learning contracts;
- point-in-time, network-denied Parquet fixture client;
- batch fixture and deterministic historical forecast providers;
- confidence/probability/volatility portfolio construction;
- position, gross, net, turnover, cash, sector, strategy, stale-price, shorting, and leverage controls;
- deterministic commission/slippage simulation with atomic batch validation;
- canonical cycle receipts and tamper-evident idempotent SQLite ledger;
- full reproducibility manifest with code/tree/lock/data/evidence/model/cost hashes;
- weekly/monthly backtesting through the production cycle path;
- no-key CLI and offline acceptance tests.

The next release adds the replayable LangGraph specialist desk and versioned Markdown skill harness before any web or memory integration.

## Architecture rule

```text
point-in-time snapshot and evidence
→ specialist research provider
→ evidence-linked AlphaForecast batch
→ deterministic portfolio constructor
→ immutable hard risk gate
→ simulated broker
→ append-only cycle ledger
```

The agent graph is a forecast provider. It never crosses the portfolio/risk/execution boundary.

## Specifications

- Authoritative: [`docs/AegisQuant_MVP_Capability_Upgrade_v2.md`](docs/AegisQuant_MVP_Capability_Upgrade_v2.md)
- Historical v1: [`docs/AegisQuant_MVP_Build_Spec.md`](docs/AegisQuant_MVP_Build_Spec.md)

## Provenance and license

AegisQuant began from `virattt/ai-hedge-fund` commit `eff8a7320fcf0b473b135690fa1a5b0d9b022a83`. See [`NOTICE.md`](NOTICE.md) and [`LICENSE`](LICENSE).
