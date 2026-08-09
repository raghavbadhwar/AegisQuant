# Codex Master Prompt — Build AegisQuant v3 Institutional Investment OS

You are acting as a principal quantitative-platform engineer, senior fundamental-equity analyst, valuation specialist, agent-harness architect, systematic-research lead, portfolio engineer, security engineer, and rigorous test author.

You are upgrading a completed and independently audited AegisQuant v2 repository into:

> **AegisQuant v3 — Institutional Investment Research & Multi-Strategy Fund OS**

The previous v3 prompt centred the upgrade on a persistent paper fund. This prompt supersedes it. Paper operation remains a downstream capability, but the primary upgrade is a complete calculation-backed fundamental and quantitative investment-research system.

---

## Repository preflight

Expected repository:

```text
/Users/raghav/aegisquant
```

Expected starting branch:

```text
build/aegisquant-mvp
```

Expected HEAD prefix:

```text
8cce4d5
```

User-reported v2 release state:

- clean worktree;
- Ruff format/check PASS;
- strict mypy PASS across 82 files;
- pytest PASS with 99 tests;
- focused adversarial suite PASS with 46 tests;
- independent audit PASS with no P0/P1/P2 findings;
- two isolated replays byte-identical;
- replay SHA-256:
  `d56c64245e6c7889e014e989a93ab04a86678aa674b0d5bddaadb767f1b2afd8`.

Treat these as invariants.

Run:

```bash
cd /Users/raghav/aegisquant
git status --short
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
find . -maxdepth 4 -type f | sort
```

Stop and report an exact mismatch if:

- worktree is not clean;
- branch differs;
- HEAD does not begin `8cce4d5`.

Read all repository guidance and core code before making assumptions:

```text
README.md
AGENTS.md
HARNESSES.md
pyproject.toml
docs/
policies/
agents/
skills/
src/ or package root
tests/
dashboard/
```

Map:

- run-cycle path;
- LangGraph state and nodes;
- evidence/claim graph;
- memory governance;
- ledgers and hash chains;
- data and broker protocols;
- backtesting;
- research lab;
- CLI;
- dashboard;
- test conventions.

---

## Isolated development

Create an isolated worktree:

```bash
git worktree add ../aegisquant-v3-institutional \
  -b upgrade/aegisquant-v3-institutional-os \
  8cce4d5

cd ../aegisquant-v3-institutional
```

Do not modify the v2 branch.

---

## Write architecture and plans first

Create or adapt to repository convention:

```text
docs/architecture/aegisquant-v3-institutional-os.md
docs/plans/v3a-fundamental-intelligence.md
docs/plans/v3b-quant-multistrategy.md
docs/plans/v3c-fund-operations.md
docs/plans/v3d-memory-improvement.md
```

Before code:

1. inspect actual paths and interfaces;
2. map exact files to change/create;
3. define domain contracts;
4. define release gates;
5. identify dependency additions;
6. conduct licence review;
7. write TDD tasks with focused commits.

Do not begin v3B until v3A passes. Do not begin v3C until v3B passes. Do not begin v3D until v3C passes.

---

# Core product decision

AegisQuant v3 has five first-class modes:

```text
Company Research
Screening & Watchlists
Strategy Research
Fund / Backtest / Paper
Memory & Improvement
```

Paper trading is not the identity of the system.

---

# Global invariants

1. LLMs never calculate authoritative financial values.
2. LLMs never place orders, determine fills, size positions, or override risk.
3. Every exact numerical claim links to a structured field, source coordinate, or deterministic calculation.
4. Historical research uses filing/availability timestamps, not report-period dates.
5. Raw source payloads are captured and hashed before extraction.
6. Unsupported company archetypes abstain.
7. Every valuation exposes assumptions, ranges, and sensitivity.
8. Human research dossier and backtestable forecast are separate contracts.
9. Investor personas are optional review lenses, not default alpha voters.
10. Every strategy and model attempt is recorded, including failures.
11. Candidate author cannot approve the candidate.
12. No live broker and no autonomous production promotion.
13. GBrain is never authoritative for positions, orders, cash, fills, P&L, or risk.
14. Risk may reduce or reject exposure, never increase it.
15. Existing v2 tests and replay determinism remain green.
16. Prefer focused typed modules; do not create new monoliths.
17. Use `Decimal` for valuation, cash, price, notional, and accounting where appropriate.
18. Fail loudly on inconsistent statements, ledger breaks, stale marks, or uncertain side effects.
19. Production-affecting versions support rollback.
20. Simple baselines remain mandatory.

---

# Release v3A — Fundamental Intelligence & Valuation

## Goal

Generate a point-in-time, evidence-cited, calculation-backed company research dossier and standardised fundamental forecast.

## A. Domain contracts

Create repository-native Pydantic types for:

```text
CompanyResearchRequest
CompanyArchetype
FilingFact
RawFilingSnapshot
NormalizedFinancialStatements
NormalizationAdjustment
CalculationLineage
FundamentalMetrics
BusinessModelAssessment
IndustryAssessment
AccountingQualityAssessment
ManagementTrackRecord
ForecastDriver
OperatingForecast
ValuationAssumption
DCFResult
ImpliedExpectations
ComparableValuation
SOTPResult
ScenarioValuation
FundamentalScorecard
InvestmentThesis
ThesisCheckpoint
FundamentalResearchDossier
AlphaForecast
```

Every type must be serialisable and versioned where persisted.

Do not use `dict[str, Any]` as the default architecture.

## B. Fundamental research graph

Implement or extend LangGraph:

```text
intake
→ entity resolution
→ PIT evidence snapshot
→ statement normalisation
→ company-archetype routing
→ parallel specialists
   - business/industry
   - financial quality
   - accounting quality
   - growth/drivers
   - balance sheet
   - capital allocation
   - management/guidance
   - valuation
   - catalysts/risks
→ evidence/calculation audit
→ bear/base/bull operating cases
→ thesis committee
→ forecast verification
→ dossier + AlphaForecast
```

The thesis committee receives only audited artifacts and may not fetch new facts.

## C. Raw filing and XBRL ingestion

Prefer official SEC EDGAR/company filings for US issuers.

Persist:

```text
concept
value
unit
period
filing timestamp
accepted timestamp
form
accession number
source coordinate
raw capture
revision lineage
```

Historical eligibility is based on availability time.

Never overwrite raw facts with normalised values.

## D. Statement normalisation

Implement deterministic canonical financial statements.

Required capabilities:

- issuer concept mapping;
- income/balance/cash-flow reconciliation;
- continuing operations;
- share count;
- one-time items;
- lease treatment;
- acquisition/divestiture flags;
- stock-based compensation;
- optional R&D capitalisation as an explicit analytical adjustment;
- reported and adjusted views;
- restatement tracking;
- calculation lineage.

Every adjustment is reversible and evidenced.

## E. Company archetypes

Implement a protocol/router.

Release-critical:

```text
general non-financial operating company
```

Define adapters/interfaces and explicit abstention for:

```text
SaaS/subscription
banks/financials
REITs
cyclicals/commodity producers
pre-profit companies
```

Add additional archetypes only after the general path passes.

Never apply operating-company FCFF to banks/insurers.

## F. Deterministic metrics

Implement and test:

```text
revenue/EPS/FCF growth
growth acceleration
margins and margin trend
ROIC
incremental ROIC
ROE
asset turns
reinvestment rate
cash conversion
accrual ratios
working capital
SBC dilution
capex intensity
net debt
debt/EBITDA
interest coverage
liquidity
share issuance/repurchases
dividends
M&A
per-share value creation
```

No LLM arithmetic.

## G. Operating forecast

Create deterministic statements from typed assumptions.

The agent may propose assumptions. The engine calculates.

Validate:

- segment totals;
- margin bounds;
- cash-flow reconciliation;
- growth/reinvestment consistency;
- dilution;
- bear/base/bull ordering;
- scenario assumptions and evidence.

## H. DCF

Implement or integrate behind a repository-owned adapter.

Required:

- FCFF;
- explicit years;
- discount rate/WACC;
- tax;
- reinvestment linked to growth and ROIC;
- terminal assumptions;
- net debt;
- diluted shares;
- per-share output;
- sensitivity grid;
- assumption provenance.

Tests:

- hand-computed golden cases;
- independent alternate implementation cross-check;
- property/round-trip tests;
- monotonicity;
- invalid input handling.

## I. Reverse DCF

Evaluate `implied-expectations` as an optional dependency or adapt its methodology with licence attribution.

Solve:

- implied revenue growth;
- implied growth duration;
- implied operating margin;
- optional implied ROIC/reinvestment.

Do not emit impossible values silently. Return feasibility flags and explicit limitations.

## J. Comparable valuation

Implement:

- explicit peer list and selection rationale;
- distribution of multiples;
- growth/margin/ROIC context;
- EV/revenue, EV/EBITDA, EV/EBIT, P/E, P/FCF;
- sector-specific appropriate multiples;
- no single-multiple false precision.

## K. SOTP and sector-specific hooks

Create the interface; implement SOTP only when segment data is valid.

Unsupported model requests abstain.

## L. Management/guidance track record

Track:

- issued guidance;
- revisions;
- actuals;
- bias and accuracy;
- capital-allocation promises;
- M&A outcomes;
- dilution;
- disclosure quality.

Use deterministic comparisons; agent interpretation is secondary.

## M. Living thesis ledger

Persist immutable thesis versions.

Events can strengthen, weaken, invalidate, or resolve a thesis.

Thesis contains:

- core claims;
- catalysts;
- risks;
- valuation cases;
- invalidation conditions;
- checkpoints;
- evidence;
- horizon.

## N. Fundamental scorecard and forecast

The dossier is not the signal.

Create a backtestable scorecard and `AlphaForecast` with:

```text
expected excess return
expected volatility
probability positive
confidence
uncertainty
horizon
thesis
evidence
invalidation
components
abstention
```

Add calibration hooks.

## O. Fundamental dossier

Generate Markdown/HTML/JSON containing:

```text
business
industry
financial quality
growth
accounting quality
balance sheet
capital allocation
management
forecast
DCF
reverse DCF
comps
scenarios
catalysts
risks
thesis
forecast
evidence
known gaps
```

## P. Markdown skill system

Create/update policies:

```text
FUNDAMENTAL_ANALYSIS.md
VALUATION.md
FORECASTING.md
POINT_IN_TIME.md
EVIDENCE.md
```

Create agent manifests and skills from the specification.

Markdown must reference tested Python tools. Do not embed large ad hoc financial implementations in `SKILL.md`.

## v3A release gate

Prove on frozen fixtures:

1. profitable quality company;
2. expensive growth company;
3. deteriorating cyclical;
4. accounting-quality warning;
5. unsupported financial company abstains or routes correctly.

All calculations, evidence, replay, static typing, and adversarial tests pass.

---

# Release v3B — Quant Research & Multi-Strategy Fund

## A. Universe engine

Add point-in-time universe snapshots or explicit fixed-universe fixtures.

Record listings, liquidity, sectors, data completeness, and eligibility.

## B. Factor registry

Support economic rationale, formula, lag, horizon, neutralisation, costs, version, and history.

## C. Factor evaluation

Adopt Alphalens-style outputs:

```text
IC/rank IC
ICIR
quantiles
long-short
monotonicity
turnover
autocorrelation
neutralisation
regimes
cost-adjusted results
decay
correlation/crowding
```

## D. Event studies

Integrate/extend the current event-study capability.

Require proper event timestamps and source-type segmentation.

## E. Regime and behavioral modules

Deterministic models produce features; LLMs interpret.

Behavioral output never becomes an order.

## F. Portfolio model protocol

Implement candidates:

```text
equal weight
inverse volatility
forecast-weighted
mean-risk shrinkage
risk budgeting
HRP
maximum diversification
benchmark tracking
```

Evaluate skfolio behind an adapter.

Retain a dependency-free simple fallback.

## G. Multi-strategy hierarchy

Implement:

```text
FundMandate
StrategyPod
AlphaModel
ForecastBlender
PodPortfolioPolicy
PodRiskBudget
FundAllocator
MasterPortfolio
MasterRisk
```

Suggested pods:

```text
fundamental expectations
earnings/events
systematic quality-momentum
defensive regime overlay
```

## H. Forecast blending

Weight forecasts by:

- expected return;
- uncertainty;
- model calibration;
- horizon;
- regime;
- feature overlap;
- evidence quality.

Do not average prose confidence.

## I. Validation

Integrate:

- qtype;
- purgedcv;
- walk-forward;
- CPCV;
- PBO;
- PSR/DSR;
- cost stress;
- parameter perturbation;
- baselines;
- ablations.

Record every trial.

## v3B release gate

The fund must compare:

```text
equal weight
inverse vol
simple deterministic factors
fundamental-only
quant-only
combined multi-strategy
```

No combined system is accepted merely because it is more complex.

---

# Release v3C — Monitoring and Persistent Fund Operations

Implement:

- source monitors;
- EventCandidate;
- research-case triggers;
- persistent paper broker;
- positions/cash/NAV;
- order lifecycle;
- costs and slippage;
- exchange calendar;
- idempotent cycles;
- restart reconciliation;
- dashboard fund views.

Use the same target/risk/order domain path as backtests.

No live broker.

---

# Release v3D — Memory and Governed Improvement

## A. GBrain

Integrate behind an optional typed adapter.

Store approved research memory only.

Enforce memory PIT before retrieval.

Fallback safely to local approved memory.

## B. Outcome attribution

Separate:

```text
thesis
fundamental forecast
valuation
factor/beta
timing
sizing
cost
risk intervention
external shock
```

## C. Candidate generation

Allowed:

```text
memory
skill
prompt
model route
retrieval policy
factor
fundamental metric
valuation policy
alpha model
strategy
allocator
```

Risk relaxation and broker permission are forbidden.

## D. Champion–challenger

Shadow candidates cannot affect portfolio or orders.

## E. Promotion

Human approval required.

Promotion and rollback are append-only and tamper-evident.

---

# Dependency selection

Inspect current dependencies first.

Evaluate, do not automatically add:

```text
implied-expectations
skfolio
alphalens-reloaded
vectorbt
quantstats or ffn
```

Likely add/keep:

```text
statsmodels
purgedcv
qtype dev dependency
exchange_calendars
```

For each:

- review licence;
- pin version;
- wrap behind internal protocol;
- test fallback;
- document reason.

Do not replace the audited v2 backtester just to use a popular library.

---

# Testing discipline

Use TDD and small commits.

Required fundamental tests:

```text
XBRL/fact lineage
PIT eligibility
statement reconciliation
restatement handling
adjustment reversibility
forecast arithmetic
DCF golden cases
DCF round-trip
reverse DCF recovery
valuation monotonicity
scenario ordering
unsupported-archetype abstention
numerical citation
```

Required graph tests:

```text
tool authority
parallel specialists
audit block
committee no-new-facts
historical future exclusion
injection quarantine
replay determinism
```

Required quant/fund tests:

```text
factor lag
universe PIT
event CAR
purging/embargo
PBO/DSR
portfolio constraints
pod netting
master risk
cash/NAV conservation
```

Required learning tests:

```text
all trials recorded
no self-approval
no shadow impact
promotion required
rollback
lucky outcome not auto-learned
```

After each task:

1. failing test;
2. expected failure;
3. minimal implementation;
4. focused test;
5. integration/adversarial tests;
6. commit.

Suggested commit sequence:

```text
feat(fundamentals): add filing facts and PIT lineage
feat(fundamentals): normalize financial statements
feat(fundamentals): add company archetype routing
feat(fundamentals): compute quality and accounting metrics
feat(forecast): add driver-based operating forecasts
feat(valuation): add FCFF DCF and sensitivities
feat(valuation): add reverse DCF implied expectations
feat(valuation): add comparable valuation
feat(research): add fundamental specialist graph
feat(thesis): add living thesis and management records
feat(forecast): emit calibrated fundamental alpha forecasts
feat(screening): add PIT universe and fundamental screens
feat(factors): add institutional factor diagnostics
feat(portfolio): add portfolio model protocol and skfolio adapter
feat(fund): add strategy pods and allocator
feat(operations): add monitoring and persistent paper book
feat(memory): add thesis-aware GBrain projection
feat(learning): add champion-challenger promotion
feat(ui): add research, valuation, quant, and fund workspaces
docs: document institutional v3 architecture
```

Adapt to actual repository paths.

---

# Final verification

At completion:

1. Ruff format/check;
2. strict mypy;
3. all unit/integration/adversarial/property tests;
4. frozen fundamental golden cases;
5. two isolated byte-identical replays;
6. end-to-end company dossier;
7. end-to-end strategy backtest;
8. multi-strategy portfolio comparison;
9. paper-cycle fixture;
10. candidate shadow/promotion fixture;
11. independent audit focused on:
   - PIT leakage;
   - valuation arithmetic;
   - numerical provenance;
   - unsupported company archetypes;
   - prompt injection;
   - agent authority;
   - portfolio/risk bypass;
   - experiment selection bias;
   - promotion bypass;
12. clean worktree;
13. report final commit, commands, test counts, hashes, and limitations.

---

# Explicit non-goals

Do not add:

- live broker;
- autonomous promotion;
- HFT;
- market making;
- options or fixed-income portfolio;
- all global markets;
- Kubernetes/Kafka/Temporal;
- dedicated graph/vector database;
- persona voting as the investment process;
- unsupported precise price targets;
- large unrelated refactors.

---

# Definition of done

AegisQuant v3 is done when it is demonstrably:

- a deep company-research and valuation system;
- a quantitative research and validation system;
- a multi-strategy portfolio/fund engine;
- capable of replay, backtest, current research, and paper operation;
- point-in-time and evidence honest;
- calculation-backed rather than prompt-only;
- memory-enriched but ledger isolated;
- self-improving only through evaluation and human promotion;
- reproducible and independently auditable.

Begin by inspecting the repository and writing the four implementation plans. Do not code from assumptions.
