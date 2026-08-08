# AegisQuant MVP — Build Specification

## 1. Product definition

AegisQuant is an evidence-first, skill-driven, hierarchical agentic investment research and paper-trading system. It combines:

- a real fund hierarchy: Fund → Strategy Pods → Alpha Models → Forecasts;
- a stateful LangGraph research desk with specialist agents;
- Markdown-defined skills and agent policies;
- point-in-time data and evidence provenance;
- deterministic portfolio construction, risk limits, and simulated execution;
- end-to-end backtesting through the same cycle used for paper runs;
- GBrain-backed long-term research memory;
- Agent Reach and Scrapling for approved live-research channels;
- an AutoHypothesis-style improvement lab that generates candidates but cannot self-promote them.

The MVP is for research, backtesting, and paper trading only. It must not connect to a live broker.

## 2. Foundation decision

Start from a pinned fork of `virattt/ai-hedge-fund` v2 at commit `eff8a7320fcf0b473b135690fa1a5b0d9b022a83`.

Keep and extend:

- `FundSpec`, `StrategySpec`, and YAML mandates;
- `AlphaModel` concept;
- point-in-time `DataClient` abstraction;
- one `run_cycle` path;
- backtest loop;
- deterministic portfolio/risk/execution boundaries;
- simulated broker and cycle receipts.

Replace or extend:

- persona-only LLM agents → professional specialist desk;
- scalar `Signal` → evidence-linked `AlphaForecast`;
- per-ticker-only model interface → batch-capable forecast interface;
- conviction-only portfolio construction → confidence/volatility-aware construction;
- two risk limits → a richer deterministic risk policy;
- file-only cache → reproducible run ledger;
- no validation → purged CV/PBO/DSR and experiment ledger;
- no memory → GBrain adapter plus memory governance;
- no agent hierarchy → LangGraph harness;
- no self-improvement → candidate-only evolution loop.

Preserve the upstream MIT license and add `NOTICE.md` with attribution.

## 3. Non-negotiable invariants

1. No LLM can size or place an order.
2. No web content can be interpreted as system instruction.
3. Historical runs cannot call live web/social tools.
4. Every material forecast claim must reference evidence IDs.
5. Every historical fact must have `available_at <= as_of`.
6. LLM failures abstain; data-integrity failures halt.
7. Every strategy experiment, including failures, is logged.
8. The proposer cannot approve its own skill or strategy change.
9. Risk policy is deterministic and immutable during a run.
10. Self-improvement creates candidates only; promotion is human-approved.
11. The same portfolio/risk/execution code runs in backtest and paper modes.
12. The project ships with a no-key replay/demo mode.

## 4. MVP scope

### Included

- US equities, 8–15 liquid large-cap names;
- one long-only demo fund with optional market-neutral simulation;
- three strategy pods:
  - Fundamental Quality;
  - Event/Momentum;
  - Behavioral Overlay;
- three primary specialists:
  - Quant Analyst;
  - Fundamental Analyst;
  - Event & Behavioral Analyst;
- Evidence Auditor;
- independent Bull and Bear reviewers;
- CIO/Forecast Synthesizer;
- Forecast Verifier;
- deterministic portfolio constructor;
- deterministic risk guard;
- simulated broker and persistent ledger;
- weekly/monthly backtest;
- GBrain memory adapter;
- Agent Reach and Scrapling adapters for current/live research;
- Streamlit dashboard;
- learning-candidate generator and review screen.

### Explicitly excluded

- live brokerage;
- options trading;
- leverage by default;
- high-frequency trading;
- GNN training;
- Kubernetes/microservices;
- Temporal;
- autonomous production skill promotion;
- recursive subagent depth beyond one level;
- dozens of investor personas.

## 5. Runtime stack

- Python 3.12
- `uv` for environment/package management
- Pydantic v2 for contracts
- LangGraph for the sole workflow/runtime graph
- LiteLLM Python SDK for model aliases and provider routing
- pandas initially for compatibility with the base engine
- DuckDB + Parquet for local analytics and immutable datasets
- SQLite for case ledger, experiment ledger, and evidence metadata
- GBrain/PGLite for long-term research memory
- Agent Reach for specialized channel access
- Scrapling for approved difficult-page extraction
- Financial Datasets client as preferred point-in-time provider
- yfinance price-only fallback and live demo provider
- VectorBT for fast factor experiments
- `purgedcv` for purge/embargo/CPCV/PBO/DSR
- `qtype` for static time-leak checks
- Streamlit + Plotly for the dashboard
- pytest, Ruff, mypy, pre-commit

## 6. Repository layout

```text
aegisquant/
├── README.md
├── NOTICE.md
├── AGENTS.md
├── HARNESSES.md
├── pyproject.toml
├── .env.example
│
├── apps/
│   ├── cli.py
│   └── dashboard.py
│
├── aegis/
│   ├── contracts/
│   │   ├── case.py
│   │   ├── evidence.py
│   │   ├── artifacts.py
│   │   ├── forecasts.py
│   │   ├── portfolio.py
│   │   ├── risk.py
│   │   ├── execution.py
│   │   └── learning.py
│   │
│   ├── harness/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── planner.py
│   │   ├── skill_loader.py
│   │   ├── model_router.py
│   │   ├── capability_broker.py
│   │   └── checkpoints.py
│   │
│   ├── agents/
│   │   ├── coordinator.py
│   │   ├── quant.py
│   │   ├── fundamentals.py
│   │   ├── event_behavioral.py
│   │   ├── evidence_auditor.py
│   │   ├── bull.py
│   │   ├── bear.py
│   │   ├── cio.py
│   │   ├── forecast_verifier.py
│   │   └── postmortem.py
│   │
│   ├── data/
│   │   ├── protocol.py
│   │   ├── financial_datasets.py
│   │   ├── yfinance_prices.py
│   │   ├── fixtures.py
│   │   ├── snapshots.py
│   │   └── policies.py
│   │
│   ├── sources/
│   │   ├── gateway.py
│   │   ├── agent_reach.py
│   │   ├── scrapling.py
│   │   ├── direct_http.py
│   │   └── normalization.py
│   │
│   ├── evidence/
│   │   ├── ledger.py
│   │   ├── claims.py
│   │   ├── graph.py
│   │   ├── validators.py
│   │   └── injection_scan.py
│   │
│   ├── memory/
│   │   ├── protocol.py
│   │   ├── gbrain.py
│   │   ├── local.py
│   │   ├── retrieval.py
│   │   └── governance.py
│   │
│   ├── fund/
│   │   ├── spec.py
│   │   ├── models.py
│   │   ├── run_cycle.py
│   │   ├── ledger.py
│   │   └── allocator.py
│   │
│   ├── quant/
│   │   ├── factors.py
│   │   ├── event_study.py
│   │   ├── behavioral.py
│   │   ├── calibration.py
│   │   ├── portfolio.py
│   │   ├── costs.py
│   │   └── metrics.py
│   │
│   ├── risk/
│   │   ├── policy.py
│   │   ├── checks.py
│   │   └── signatures.py
│   │
│   ├── brokers/
│   │   ├── protocol.py
│   │   └── simulated.py
│   │
│   ├── lab/
│   │   ├── program.py
│   │   ├── sandbox.py
│   │   ├── experiments.py
│   │   ├── validation.py
│   │   ├── candidates.py
│   │   └── promotion.py
│   │
│   └── reporting/
│       ├── html.py
│       ├── charts.py
│       └── dossier.py
│
├── skills/
│   ├── core/
│   │   ├── case-planning/SKILL.md
│   │   ├── evidence-protocol/SKILL.md
│   │   └── point-in-time-safety/SKILL.md
│   ├── research/
│   │   ├── quant-signal-analysis/SKILL.md
│   │   ├── fundamental-quality-valuation/SKILL.md
│   │   ├── event-behavioral-reaction/SKILL.md
│   │   ├── bull-case/SKILL.md
│   │   ├── bear-case/SKILL.md
│   │   └── cio-synthesis/SKILL.md
│   ├── validation/
│   │   ├── forecast-audit/SKILL.md
│   │   ├── factor-evaluation/SKILL.md
│   │   └── strategy-validation/SKILL.md
│   └── learning/
│       ├── postmortem/SKILL.md
│       └── candidate-refinement/SKILL.md
│
├── agents/
│   ├── coordinator/AGENT.md
│   ├── quant-analyst/AGENT.md
│   ├── fundamental-analyst/AGENT.md
│   ├── event-behavioral-analyst/AGENT.md
│   ├── evidence-auditor/AGENT.md
│   ├── bull-reviewer/AGENT.md
│   ├── bear-reviewer/AGENT.md
│   ├── cio/AGENT.md
│   └── postmortem/AGENT.md
│
├── policies/
│   ├── EVIDENCE_POLICY.md
│   ├── MEMORY_POLICY.md
│   ├── MODEL_ROUTING.md
│   ├── RISK_POLICY.md
│   └── SELF_IMPROVEMENT_POLICY.md
│
├── configs/
│   ├── funds/demo-fund.yaml
│   ├── models.yaml
│   ├── sources.yaml
│   └── risk.yaml
│
├── research_lab/
│   ├── program.md
│   ├── candidates/
│   ├── results/
│   └── holdout.lock
│
├── demo_data/
│   ├── prices.parquet
│   ├── fundamentals.parquet
│   ├── earnings.parquet
│   └── evidence/
│
├── evals/
│   ├── agent_cases.yaml
│   ├── evidence_cases.yaml
│   ├── routing_cases.yaml
│   ├── replay_cases.yaml
│   └── backtest_baselines.yaml
│
└── tests/
    ├── unit/
    ├── integration/
    ├── replay/
    ├── backtest/
    ├── security/
    └── acceptance/
```

## 7. LangGraph workflow

```text
START
  ↓
intake_case
  ↓
freeze_point_in_time_snapshot
  ↓
recall_approved_memory
  ↓
plan_research
  ↓
parallel specialists
  ├─ quant analyst
  ├─ fundamental analyst
  └─ event/behavioral analyst
  ↓
evidence_audit
  ├─ insufficient and retry_budget > 0 → source_gateway → specialists
  ├─ invalid → abstain/halt
  └─ sufficient
       ↓
parallel independent reviews
  ├─ bull memo
  └─ bear memo
       ↓
cio_synthesis
       ↓
forecast_verifier
  ├─ failed → abstain/human review
  └─ passed
       ↓
deterministic_portfolio_constructor
       ↓
hard_risk_gate
  ├─ reject → ledger
  └─ approve
       ↓
simulated_broker
       ↓
cycle_ledger
       ↓
backtest/outcome_evaluation
       ↓
learning_candidate_generation
       ↓
END
```

Specialists run in parallel. Bull and Bear independently draft opening memos before seeing each other. One rebuttal round is optional and only runs when the contradiction score exceeds a threshold.

## 8. Execution modes

### Replay mode

- no network;
- demo fixtures and cached model outputs;
- deterministic and recruiter-friendly;
- required for CI.

### Historical mode

- only point-in-time-safe structured sources;
- Agent Reach, Scrapling, and current GBrain memories disabled unless they existed at `as_of`;
- same cycle path as paper mode.

### Live research mode

- current data;
- approved Agent Reach channels and Scrapling pages allowed;
- still simulated execution only.

## 9. Core contracts

### EvidenceRecord

```python
class EvidenceRecord(BaseModel):
    evidence_id: str
    source_type: str
    source_url: str | None
    entity_ids: list[str]
    document_type: str
    published_at: datetime | None
    available_at: datetime
    ingested_at: datetime
    raw_object_uri: str
    content_hash: str
    historical_safe: bool
    source_quality: float
    extraction_confidence: float
    prompt_injection_flags: list[str]
```

### AlphaForecast

```python
class AlphaForecast(BaseModel):
    model_name: str
    ticker: str
    as_of: date
    horizon_days: int
    expected_excess_return: float | None
    expected_volatility: float | None
    probability_positive: float
    confidence: float
    uncertainty: float
    thesis: str
    evidence_ids: list[str]
    invalidation_conditions: list[str]
    abstained: bool = False
    abstain_reason: str | None = None
    components: dict[str, float] = {}
```

### ResearchArtifact

```python
class ResearchArtifact(BaseModel):
    artifact_id: str
    case_id: str
    artifact_type: str
    producer_agent: str
    model_alias: str
    actual_model: str
    skill_versions: list[str]
    evidence_ids: list[str]
    payload: dict
    warnings: list[str]
    content_hash: str
```

### RiskDecision

```python
class RiskDecision(BaseModel):
    approved: bool
    final_weights: dict[str, float]
    violations: list[str]
    warnings: list[str]
    policy_version: str
    input_hash: str
```

### LearningCandidate

```python
class LearningCandidate(BaseModel):
    candidate_id: str
    candidate_type: Literal["memory", "skill", "prompt", "strategy"]
    target_path: str | None
    proposed_patch: str
    triggering_run_ids: list[str]
    evidence_ids: list[str]
    expected_improvement: str
    falsifiable_metric: str
    evaluation_status: str
    promotion_status: str = "candidate_only"
```

## 10. Skill standard

Every `SKILL.md` must contain:

```yaml
---
name: fundamental-quality-valuation
version: 1.0.0
description: Point-in-time company quality and valuation analysis.
owner: research
roles: [fundamental-analyst]
inputs: [FundamentalsSnapshot, EvidenceBundle]
outputs: [FundamentalAssessment]
allowed_tools:
  - data.financial_metrics
  - data.company_facts
  - evidence.lookup
historical_safe: true
memory_read: [company, management, prior-cases]
memory_write: candidate-only
model_alias: research-standard
max_tool_calls: 8
max_cost_usd: 0.50
---
```

Required body sections:

1. Objective
2. Non-goals
3. Preconditions
4. Inputs
5. Allowed tools
6. Procedure
7. Deterministic calculations
8. Evidence contract
9. Abstention and halt conditions
10. Output contract
11. Verification checklist
12. Known failure modes
13. Memory policy
14. Evaluation cases
15. Version history

Skills must not contain large untested Python implementations. They reference tested Python tools/functions. Markdown defines reasoning protocol; code performs calculations and side effects.

## 11. Initial agent roster

### Coordinator

- selects the smallest specialist set;
- assigns budgets and capabilities;
- cannot make the final forecast.

### Quant Analyst

- interprets deterministic momentum, volatility, PEAD, liquidity, and relative-strength features;
- may not calculate by hand;
- outputs QuantAssessment.

### Fundamental Analyst

- evaluates quality, financial trend, balance sheet, valuation, and management guidance;
- point-in-time only;
- outputs FundamentalAssessment.

### Event & Behavioral Analyst

- classifies catalysts, attention, narrative disagreement, and reaction path;
- uses web tools only in live mode;
- outputs BehavioralEventAssessment.

### Evidence Auditor

- verifies provenance, dates, exact numbers, contradictions, and source quality;
- can block the case.

### Bull and Bear Reviewers

- independently construct strongest evidence-backed cases;
- no tools;
- no fabricated opponent arguments.

### CIO

- synthesizes verified artifacts into AlphaForecast;
- cannot introduce new facts;
- must state uncertainty and invalidation conditions.

### Forecast Verifier

- checks schema, evidence coverage, numeric consistency, confidence, and horizon;
- can force abstention.

### Postmortem Agent

- reads matured outcomes and attribution;
- proposes learning candidates only;
- cannot edit production skills.

## 12. Data and source policy

### Preferred order

1. local canonical snapshot;
2. official/licensed API;
3. official filing/exchange page;
4. direct HTTP/RSS;
5. Agent Reach channel;
6. Scrapling;
7. isolated browser/manual review.

All source outputs normalize into EvidenceRecord.

Agent Reach is wrapped behind typed tools. Scrapling runs in a restricted subprocess/container with domain allowlists, limits, and no secrets except source-specific credentials.

## 13. Memory system

Use a `MemoryBackend` protocol with:

- `GBrainMemoryBackend` as the preferred long-term memory store;
- `LocalMemoryBackend` as the deterministic CI/replay fallback.

Memory types:

- semantic facts;
- episodic cases;
- procedural lessons;
- regime lessons;
- negative memory;
- actor/management credibility;
- counterfactual outcomes.

Only approved memory is written to GBrain. Historical cases may only retrieve memory whose `available_at <= case.as_of`.

## 14. Portfolio construction

MVP policy: confidence- and volatility-adjusted forecast weighting.

1. Reject abstained forecasts and forecasts below minimum confidence.
2. Convert expected excess return and probability-positive into a normalized score.
3. Divide by recent volatility.
4. Cross-sectionally normalize.
5. Apply long-only or market-neutral policy.
6. Target 80–90% gross exposure, retaining a cash buffer.
7. Apply risk caps.

Default demo risk:

- max position 15%;
- max gross 90%;
- max turnover per cycle 30%;
- min cash 10%;
- no leverage;
- no shorting in default demo;
- stale price or missing held-position price halts the cycle;
- fees and slippage always enabled.

## 15. Research lab and self-improvement

Adopt an AutoHypothesis-style fixed/editable boundary.

### Locked

- data loaders;
- point-in-time rules;
- simulator;
- metrics;
- risk;
- holdout dates;
- experiment ledger;
- promotion logic.

### Editable by candidate agent

- `strategies/candidates/*.py`;
- `skills/candidates/*/SKILL.md`;
- candidate prompt/routing configs.

### Required loop

1. Read `research_lab/program.md` and all prior experiments.
2. Declare economic hypothesis before code.
3. Run qtype/static checks.
4. Iterate on development period only.
5. One-shot holdback gate.
6. One-shot walk-forward/CPCV gate.
7. Calculate PBO, DSR, turnover, drawdown, and costs.
8. Generate candidate diff.
9. Shadow/replay evaluation.
10. Human promotion only.

No result may disappear from the experiment ledger.

## 16. Dashboard

Tabs:

1. Run Case
2. Agent Graph
3. Evidence Dossier
4. Forecast & Disagreement
5. Portfolio & Risk
6. Backtest & Baselines
7. Memory Recall
8. Learning Candidates

The dashboard must show source timestamps, abstentions, risk clamps, and model/skill versions—not only final BUY/SELL labels.

## 17. Required baselines and ablations

Baselines:

- SPY;
- equal-weight universe;
- momentum-only;
- fundamentals-only;
- no-agent deterministic composite.

Ablations:

- no Bull/Bear stage;
- no memory;
- no behavioral agent;
- one model for all agents vs heterogeneous models;
- raw conviction weighting vs calibrated forecast weighting.

Report both performance and operational metrics:

- Sharpe/Sortino/CAGR/max drawdown;
- turnover and cost;
- hit rate and calibration;
- abstention rate;
- evidence-coverage rate;
- LLM calls, tokens, cost, latency;
- reproducibility rate;
- risk clamp frequency.

## 18. Milestones and exit gates

### Milestone A — deterministic engine

- pinned base fork;
- updated contracts;
- batch forecasts;
- simulated broker;
- ledger;
- demo fixture client.

Exit: no-key one-cycle run and backtest pass.

### Milestone B — skill-first graph

- LangGraph state;
- skill loader;
- coordinator + three specialists;
- typed artifacts;
- bull/bear + CIO + verifier;
- replay model provider.

Exit: deterministic replay case produces a full dossier.

### Milestone C — evidence/web/memory

- EvidenceRecord and claim graph;
- Agent Reach adapter;
- Scrapling adapter;
- injection scan;
- GBrain adapter;
- historical-mode tool prohibition.

Exit: live case uses web evidence; historical case cannot.

### Milestone D — validation lab

- qtype;
- VectorBT factor evaluation;
- purgedcv/CPCV/PBO/DSR;
- trial ledger;
- baselines and ablations.

Exit: one candidate strategy either passes honestly or is rejected with reasons.

### Milestone E — self-improvement and presentation

- postmortem;
- candidate skill diff;
- replay evaluation;
- Streamlit dashboard;
- architecture and demo documentation.

Exit: a completed backtest creates a non-promoted learning candidate visible in the dashboard.

## 19. Acceptance criteria

- Fresh clone runs in replay mode with one command and no API keys.
- Same replay inputs produce byte-identical forecast and cycle records.
- Historical mode blocks Agent Reach/Scrapling and future memory.
- Every material forecast claim has an evidence ID.
- Exact numbers point to structured fields or table coordinates.
- Data failures halt; LLM failures abstain.
- Bull/Bear openings are independent.
- Risk clamps are deterministic and fully logged.
- Orders reconcile to positions/cash/NAV in SimBroker.
- Backtest uses the same `run_cycle` path as paper mode.
- Every experiment is logged, including rejected variants.
- A learning candidate cannot promote itself.
- Unit, integration, replay, security, and acceptance tests pass.

## 20. Demo commands

```bash
uv sync
uv run pytest

# No-key deterministic demo
uv run aegis replay demo_data/cases/nvda_earnings_case.json

# Current research case
uv run aegis research \
  --fund configs/funds/demo-fund.yaml \
  --tickers AAPL,MSFT,NVDA,AMZN,GOOGL \
  --mode live-research

# End-to-end historical backtest
uv run aegis backtest \
  --fund configs/funds/demo-fund.yaml \
  --tickers AAPL,MSFT,NVDA,AMZN,GOOGL \
  --start 2023-01-01 \
  --end 2025-12-31

# Dashboard
uv run streamlit run apps/dashboard.py
```

## 21. README/demo narrative

Tagline:

> Evidence-first agentic investment research, honest backtesting, deterministic risk, and governed self-improvement.

Five-minute demo:

1. Open the fund mandate.
2. Run a point-in-time case.
3. Watch specialist nodes execute in the graph.
4. Inspect claims and evidence timestamps.
5. Compare Bull and Bear memos.
6. Show calibrated forecast and uncertainty.
7. Show deterministic portfolio/risk clamps.
8. Run/replay the backtest against baselines.
9. Open the outcome postmortem.
10. Show a staged skill-improvement candidate that cannot auto-promote.

## 22. CV bullets after implementation

- Architected and built AegisQuant, a stateful LangGraph-based multi-agent investment research and paper-trading platform combining point-in-time data, evidence-cited specialist analysis, deterministic portfolio construction, risk controls, and end-to-end backtesting.
- Designed a skill-first agent framework using versioned Markdown protocols, typed Pydantic artifacts, capability-scoped tools, independent Bull/Bear review, model routing, and replayable case ledgers.
- Implemented a governed research-improvement loop with qtype static leakage checks, purged/CPCV validation, PBO/deflated Sharpe metrics, GBrain memory, and human-gated skill/strategy promotion.

## 23. Build priority

Build in this order:

1. deterministic replayable cycle;
2. typed artifacts and skill loader;
3. hierarchical graph;
4. evidence audit;
5. backtest and validation;
6. memory and self-improvement;
7. live web research;
8. dashboard polish.

Do not begin with Agent Reach, Scrapling, GBrain, or an elaborate UI. The first proof is a reproducible, point-in-time, end-to-end run in which agents form evidence-linked views and deterministic code constructs and simulates the portfolio.
