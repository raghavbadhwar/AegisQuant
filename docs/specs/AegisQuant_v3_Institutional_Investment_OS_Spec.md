# AegisQuant v3 — Institutional Investment Research & Multi-Strategy Fund OS

**Status:** Authoritative next-upgrade specification  
**Supersedes:** `AegisQuant_v3_Upgrade_Spec.md` focused primarily on paper-fund operations  
**Starting repository:** `/Users/raghav/aegisquant`  
**Starting branch:** `build/aegisquant-mvp`  
**Starting commit:** `8cce4d5`  
**Target branch:** `upgrade/aegisquant-v3-institutional-os`

---

# Executive decision

AegisQuant v2 is already a credible agentic quantitative MVP. The next upgrade should not be defined as “add paper trading.” Paper operation remains useful, but it is only one downstream mode.

The next system should be:

> **An evidence-first institutional investment operating system that can discover companies and events, perform calculation-backed fundamental and quantitative research, maintain living investment theses, build and validate multi-strategy portfolios, backtest and paper-operate the same fund, and improve its research procedures through governed evaluation.**

The product has five first-class capabilities:

1. **Fundamental Research:** company, industry, accounting, forecasting, valuation, management, catalysts, and risks.
2. **Quantitative Research:** factors, regimes, events, behavioral signals, graph features, validation, and portfolio models.
3. **Investment Decisioning:** standardised forecasts, thesis tracking, portfolio construction, risk, and allocation.
4. **Fund Operations:** replay, historical backtest, current monitoring, and persistent paper-book execution.
5. **Research Learning:** memory, post-mortems, candidate skills/models/strategies, shadow evaluation, and human promotion.

Paper trading is therefore a **mode**, not the architectural centre.

---

# 1. Benchmark synthesis and lessons adopted

## 1.1 AI Hedge Fund

Adopt its strongest structural ideas:

```text
FUND
    = allocator over STRATEGIES

STRATEGY
    = portfolio policy over ALPHA MODELS

ALPHA MODEL
    = produces a view/forecast, never an order
```

Also preserve:

- one financial cycle across replay, backtest, paper, and future execution modes;
- point-in-time data boundaries;
- deterministic portfolio construction and risk;
- serialisable fund and strategy mandates;
- pluggable data and broker protocols;
- persistent ledgers and research receipts.

Upgrade its weaker areas:

- persona prompts are not a sufficient fundamental-analysis engine;
- a scalar `[-1,+1]` conviction is too weak;
- current risk and portfolio policies are too simple;
- valuation, management credibility, industry analysis, scenario modelling, and accounting quality need explicit deterministic engines;
- analyst outputs must contain horizon, expected return, uncertainty, evidence, assumptions, and invalidation conditions.

Investor-persona agents may remain as optional **philosophy lenses**, but they are not the main analytical pipeline and do not receive portfolio weight merely for being named after famous investors.

## 1.2 Awesome Quant

Use the repository as the component taxonomy and selection benchmark.

Adopt or evaluate:

- NumPy, SciPy, Polars/Pandas, DuckDB, statsmodels;
- qtype for obvious quantitative time-leak patterns;
- purgedcv for purging, embargo, CPCV, PBO, PSR, DSR;
- skfolio for portfolio-model selection, cross-validation, stress testing, and robust optimisation;
- Alphalens-style IC/ICIR, quantile, turnover, and factor-decay analysis;
- VectorBT-style fast hypothesis testing where the current engine does not already provide an equivalent;
- exchange calendars rather than weekday arithmetic;
- performance-report tooling such as QuantStats/ffn where useful;
- `implied-expectations` methodology for reverse DCF and market-implied assumptions.

Do not add every package in the list. Each dependency must replace meaningful internal complexity or improve correctness.

## 1.3 Reverse DCF / implied expectations

A conventional DCF asks:

```text
What is the company worth under my assumptions?
```

A reverse DCF asks:

```text
What revenue growth, margin, duration, and reinvestment economics
does the current market price already require?
```

AegisQuant must perform both.

The reverse DCF should be a first-class component because it converts valuation from a fragile point estimate into a falsifiable expectations question.

## 1.4 AutoHypothesis, Alpha Skills, purgedcv, and qtype

Adopt:

- Markdown procedures as reusable research skills;
- explicit hypothesis declaration before code;
- a locked evaluation core and editable candidate surface;
- full experiment history, including failures;
- one-shot holdback and forward validation;
- purging/embargo where labels overlap;
- PBO and DSR before strategy promotion;
- factor monitoring and decay detection;
- static preflight checks before expensive backtests.

Strengthen:

- no autonomous registration of factors or strategies based only on recent IC or an LLM intuition score;
- no candidate may influence the production portfolio before human promotion;
- all research attempts remain visible in the trial ledger.

---

# 2. Product modes

AegisQuant v3 exposes five modes through one consistent application.

## 2.1 Company Research Mode

Example:

```bash
aegisquant research company NVDA --as-of 2026-08-07 --depth deep
```

Produces:

- point-in-time company and filing snapshot;
- industry and competitor map;
- normalised financial statements;
- accounting-quality assessment;
- historical operating-driver decomposition;
- management and guidance track record;
- base/bull/bear operating forecasts;
- DCF, reverse DCF, multiples, and optional SOTP;
- catalysts, risks, thesis, and invalidation conditions;
- standardised `AlphaForecast`;
- complete cited research dossier.

It does not require that the security belongs to an active fund.

## 2.2 Screening and Watchlist Mode

Example:

```bash
aegisquant screen run configs/screens/quality-expectations-gap.yaml
```

Ranks an eligible universe using:

- deterministic fundamental factors;
- quantitative factors;
- earnings/event signals;
- expectations gap;
- liquidity and risk;
- optional agent review of the top candidates.

The expensive research graph is reserved for shortlisted names.

## 2.3 Strategy Research Mode

Example:

```bash
aegisquant lab evaluate strategies/candidates/quality-expectations-gap.yaml
```

Runs:

- point-in-time features;
- factor diagnostics;
- backtests;
- purged and walk-forward validation;
- transaction-cost stress;
- portfolio-model comparisons;
- PBO/DSR;
- baseline and ablation comparisons.

## 2.4 Fund Mode

Example:

```bash
aegisquant fund backtest configs/funds/aegis-institutional.yaml
aegisquant fund run configs/funds/aegis-institutional.yaml --as-of now
aegisquant paper start aegis-institutional
```

The fund combines several strategy pods, nets their target sleeves, applies master risk, and records the book.

## 2.5 Learning Mode

Example:

```bash
aegisquant learn outcomes --matured
aegisquant learn dream --dry-run
aegisquant promotions review <candidate_id>
```

Produces evaluated candidates but never autonomously changes production.

---

# 3. Release programme

The upgrade is divided into four independently releasable increments.

## v3A — Fundamental Intelligence & Valuation

Build:

- company-data snapshot;
- statement normalisation and provenance;
- business and industry research;
- deterministic financial metrics;
- accounting-quality analysis;
- operating forecast engine;
- DCF and reverse DCF;
- comparable valuation;
- scenario and sensitivity analysis;
- management/guidance track record;
- living thesis ledger;
- fundamental research graph and dossier;
- backtestable `FundamentalAlphaModel`.

**Release gate:** AegisQuant can generate a fully cited, point-in-time, calculation-backed research dossier and standardised forecast for a general non-financial US company.

## v3B — Quant Research & Multi-Strategy Portfolio

Build:

- investable-universe and screening engine;
- factor registry and factor diagnostics;
- event-study integration;
- market-regime engine;
- behavioral and graph features;
- standardised multi-model forecasts;
- skfolio-backed portfolio-model comparison;
- strategy pods and fund allocator;
- cross-validation and robust portfolio selection;
- baseline and ablation reporting.

**Release gate:** the same universe can be evaluated by deterministic fundamental, event, and quantitative models; combined into strategy sleeves; and validated against simple baselines.

## v3C — Persistent Monitoring & Paper Fund

Build:

- live-clock source monitoring;
- persistent paper book;
- scheduler and market calendar;
- deterministic order lifecycle and costs;
- idempotent cycles;
- restart recovery and reconciliation;
- research-event triggers;
- source/memory/fund dashboards.

**Release gate:** the fund can run for at least 20 fixture cycles, survive restart, reconcile its book, and create research cases from monitored events without duplicate orders.

## v3D — Institutional Memory & Governed Improvement

Build:

- GBrain-backed approved research memory;
- living thesis updates;
- forecast maturity and attribution;
- management-credibility and model-calibration memory;
- candidate skill/prompt/model/feature/strategy generation;
- champion–challenger shadow evaluation;
- human promotion and rollback;
- dream-cycle consolidation.

**Release gate:** a candidate can progress from evidence-backed proposal to evaluation and shadow comparison, but cannot activate without a signed human promotion event.

---

# 4. Non-negotiable invariants

1. Backtest, replay, current research, and paper mode share the same financial domain contracts.
2. LLMs do not calculate authoritative financial metrics.
3. LLMs do not size positions, place orders, determine fills, or override risk.
4. Exact numerical claims trace to data fields, filing coordinates, or deterministic calculations.
5. Historical analysis sees only information, classifications, relationships, and memories available at the case time.
6. Raw filings, pages, tables, transcripts, and data payloads are captured before extraction or summarisation.
7. Unsupported sectors or data conditions produce an explicit abstention.
8. Every valuation exposes its assumptions and sensitivity.
9. A research dossier and a backtestable forecast are separate outputs.
10. Every strategy attempt is recorded, including failures.
11. The candidate author cannot approve the candidate.
12. GBrain stores research knowledge, never authoritative fund accounting.
13. Current v2 tests, replay determinism, hash-chain integrity, and static-quality gates remain release requirements.
14. No live-money broker in v3.
15. No autonomous production promotion.
16. No “famous investor vote” enters the portfolio without an evaluated forecast contract.
17. Simple baselines remain mandatory competitors.
18. Risk may reduce or reject exposure, never increase it.
19. Financial and research state transitions are versioned and replayable.
20. Every production-affecting version supports rollback.

---

# 5. Target architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│ AEGISQUANT CONTROL & EXPERIENCE                                │
│ CLI · Streamlit · scheduler · cases · approvals · reproducibility│
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ RESEARCH GRAPH                                                  │
│ intake → PIT snapshot → specialist routing → evidence audit     │
│ → thesis/valuation synthesis → forecast verification            │
└───────────────┬───────────────────────────────┬─────────────────┘
                │                               │
┌───────────────▼──────────────┐  ┌─────────────▼────────────────┐
│ FUNDAMENTAL INTELLIGENCE     │  │ QUANT INTELLIGENCE           │
│ statements · drivers ·       │  │ factors · regimes · events · │
│ forecasting · valuation ·    │  │ behavioral · graph features  │
│ management · industry        │  │ validation · calibration      │
└───────────────┬──────────────┘  └─────────────┬────────────────┘
                └───────────────┬───────────────┘
                                │ Standardised AlphaForecasts
┌───────────────────────────────▼─────────────────────────────────┐
│ MULTI-STRATEGY FUND                                             │
│ strategy pods → pod portfolios → CIO allocator → netted book    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ DETERMINISTIC PORTFOLIO & MASTER RISK                           │
│ robust optimiser · constraints · liquidity · costs · vetoes     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ FUND MODES                                                      │
│ replay · historical backtest · current recommendation · paper   │
│ execution · positions · cash · NAV · attribution                │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│ MEMORY & IMPROVEMENT                                            │
│ thesis history · GBrain projection · outcomes · candidates ·    │
│ shadow evaluation · human promotion · rollback                  │
└─────────────────────────────────────────────────────────────────┘
```

---

# 6. Fundamental Intelligence Engine

## 6.1 Design principle

The fundamental engine is not:

```text
financial ratios → persona prompt → bullish/bearish
```

It is:

```text
raw point-in-time evidence
→ statement normalisation
→ deterministic financial analysis
→ operating-driver forecasts
→ explicit valuation models
→ specialist interpretation and challenge
→ verified investment thesis
→ calibrated AlphaForecast
```

## 6.2 Fundamental research graph

```text
Company Intake
    ↓
Security / Entity Resolution
    ↓
Point-in-Time Evidence Snapshot
    ├─ filings and XBRL
    ├─ earnings releases
    ├─ transcripts and presentations
    ├─ prices / shares / capital structure
    ├─ guidance and estimates, if historically timestamped
    ├─ industry and competitor sources
    └─ corporate actions
    ↓
Statement Normaliser
    ↓
Company Archetype Router
    ↓
Parallel Specialists
    ├─ Business & Industry
    ├─ Financial Quality
    ├─ Growth & Operating Drivers
    ├─ Accounting Quality
    ├─ Balance Sheet & Liquidity
    ├─ Capital Allocation
    ├─ Management & Guidance
    ├─ Valuation
    └─ Catalysts & Risks
    ↓
Evidence and Calculation Audit
    ↓
Bull / Base / Bear Operating Cases
    ↓
Thesis Committee
    ↓
Forecast Verifier
    ↓
FundamentalResearchDossier + FundamentalAlphaForecast
```

## 6.3 Company archetypes

A single valuation model does not fit every business.

Create a typed `CompanyArchetype` router.

Initial v3 support:

### General Operating Company

Examples:

- consumer;
- industrial;
- hardware;
- healthcare;
- profitable technology.

Models:

- FCFF DCF;
- reverse DCF;
- multiples;
- optional segment SOTP.

### SaaS / Subscription

Additional drivers:

- ARR;
- net revenue retention;
- gross retention;
- customer growth;
- ARPU;
- gross margin;
- sales efficiency;
- CAC payback;
- Rule of 40;
- stock-based compensation and dilution.

Models:

- revenue/margin scenario DCF;
- reverse DCF;
- EV/revenue and EV/FCF comps;
- unit-economic plausibility.

### Banks / Financials

Do not use operating-company FCFF.

Drivers:

- ROE;
- tangible book value;
- net interest margin;
- credit costs;
- deposit mix;
- capital ratios;
- loan growth;
- asset quality.

Models:

- excess-return / residual-income;
- justified P/B;
- P/E under normalised credit costs.

### REITs

Drivers:

- NOI;
- FFO/AFFO;
- occupancy;
- rent growth;
- cap rates;
- debt maturity.

Models:

- NAV;
- AFFO multiple;
- dividend and balance-sheet analysis.

### Cyclicals / Commodity Producers

Drivers:

- price deck;
- volumes;
- unit costs;
- capacity;
- mid-cycle margin;
- balance-sheet resilience.

Models:

- normalised earnings;
- scenario NAV;
- EV/EBITDA across price decks.

The release may implement general operating companies first. Unsupported archetypes must abstain rather than force the wrong model.

## 6.4 Evidence and raw data

Preferred hierarchy:

```text
SEC EDGAR / official regulator
company filings and investor relations
official earnings releases and presentations
licensed or timestamped market/estimate data
official industry/government sources
high-quality industry research
approved public web sources
social/behavioral sources for flow only
```

For every filing fact preserve:

```python
class FilingFact(BaseModel):
    fact_id: str
    entity_id: str
    concept: str
    value: Decimal
    unit: str
    period_start: date | None
    period_end: date
    filed_at: datetime
    accepted_at: datetime | None
    form_type: str
    accession_number: str
    source_coordinate: str
    revision_id: str | None
    raw_capture_id: str
```

Historical eligibility uses `filed_at` or `accepted_at`, not fiscal period end.

## 6.5 Statement normalisation

Create a deterministic normalisation layer:

```python
class NormalizedFinancialStatements(BaseModel):
    income_statements: list[NormalizedIncomeStatement]
    balance_sheets: list[NormalizedBalanceSheet]
    cash_flows: list[NormalizedCashFlow]
    segments: list[SegmentFinancials]
    share_counts: list[ShareCountObservation]
    adjustments: list[NormalizationAdjustment]
    lineage: list[CalculationLineage]
```

Normalisation capabilities:

- map XBRL concepts to canonical fields;
- handle differing issuer tags;
- separate continuing operations;
- identify one-time charges;
- capitalise or expense R&D as an optional analytical adjustment;
- adjust leases;
- track acquisitions and divestitures;
- reconcile diluted share count;
- identify restatements;
- preserve reported and adjusted views;
- never overwrite raw facts.

Every adjustment must be explicit, reversible, and evidenced.

## 6.6 Deterministic fundamental metrics

At minimum:

### Growth

- revenue CAGR;
- organic versus acquired growth where disclosed;
- segment growth;
- EPS growth;
- FCF growth;
- growth acceleration/deceleration;
- estimate or guidance revisions where available.

### Profitability and economics

- gross, operating, EBITDA, and net margins;
- ROIC;
- incremental ROIC;
- ROE;
- asset turns;
- reinvestment rate;
- operating leverage;
- contribution margins where available.

### Cash and accounting quality

- CFO/net income;
- FCF conversion;
- accrual ratios;
- working-capital changes;
- SBC dilution;
- capex intensity;
- capitalised costs;
- one-off adjustment intensity;
- cash tax rate;
- acquisition-adjusted performance.

### Balance sheet

- net debt;
- debt/EBITDA;
- interest coverage;
- liquidity runway;
- maturity schedule where available;
- current ratio;
- working-capital resilience.

### Capital allocation

- repurchases;
- issuance;
- dividends;
- M&A;
- debt changes;
- reinvestment;
- per-share value creation.

## 6.7 Business and industry analysis

The agent layer evaluates:

- revenue model;
- customers and purchase drivers;
- products and segments;
- pricing model;
- recurring versus transactional revenue;
- market structure;
- competitors;
- suppliers and dependencies;
- regulation;
- substitution risk;
- cyclicality;
- switching costs;
- network effects;
- scale economies;
- brand;
- distribution;
- intellectual property;
- data advantages;
- management incentives.

Every qualitative claim requires evidence and a confidence level.

## 6.8 Operating forecast engine

Forecasts are structured and driver-based.

```python
class OperatingForecast(BaseModel):
    entity_id: str
    as_of: datetime
    horizon_years: int
    scenario: Literal["bear", "base", "bull"]
    revenue_drivers: list[ForecastDriver]
    margin_drivers: list[ForecastDriver]
    reinvestment_drivers: list[ForecastDriver]
    yearly_income: list[ForecastIncomeStatement]
    yearly_cash_flow: list[ForecastCashFlow]
    assumptions: list[ForecastAssumption]
    evidence_ids: list[str]
```

The agent may propose assumptions, but deterministic code generates the forecast statements and checks arithmetic identities.

Required forecast checks:

- revenue segments sum to total;
- margins remain within configured economic bounds;
- cash flow reconciles;
- growth requires plausible reinvestment;
- share dilution is reflected;
- scenario ordering is coherent;
- unsupported assumptions are flagged.

## 6.9 Valuation engine

### Forward DCF

Support:

- FCFF;
- explicit forecast period;
- WACC or configured discount rate;
- reinvestment linked to growth and ROIC;
- terminal value with explicit assumptions;
- net debt;
- diluted share count;
- per-share value;
- sensitivity matrices.

### Reverse DCF

Solve for:

- implied revenue growth;
- implied growth duration;
- implied margin;
- optional implied ROIC/reinvestment assumptions.

Output:

```python
class ImpliedExpectations(BaseModel):
    current_price: Decimal
    discount_rate: float
    horizon_years: int
    terminal_growth: float
    implied_revenue_growth: float | None
    implied_growth_duration: float | None
    implied_operating_margin: float | None
    feasibility_flags: list[str]
    assumptions: list[ValuationAssumption]
```

### Comparable valuation

- peer universe with explicit selection rationale;
- sector and business-model matching;
- EV/revenue;
- EV/EBITDA;
- EV/EBIT;
- P/E;
- P/FCF;
- P/B and ROE where appropriate;
- growth/margin/ROIC normalisation;
- median and distribution, not one multiple.

### Sum of the Parts

Optional for companies with materially different segments.

### Scenario valuation

Output bear/base/bull values and implied return distributions.

### Implied return

Calculate an expected annualised return from:

- valuation convergence;
- fundamental compounding;
- dividends/buybacks;
- dilution;
- horizon.

Do not present one “precise fair value” without a range and sensitivity.

## 6.10 Management and guidance engine

Track:

- guidance issued;
- guidance revisions;
- actual result;
- guidance accuracy;
- optimistic/pessimistic bias;
- margin/capital-allocation promises;
- acquisition claims and outcomes;
- dilution;
- buyback timing;
- insider activity where lawful data exists.

```python
class ManagementTrackRecord(BaseModel):
    entity_id: str
    guidance_events: list[GuidanceEvent]
    accuracy_by_metric: dict[str, float]
    revision_bias: dict[str, float]
    capital_allocation_score: float
    disclosure_quality_score: float
    evidence_ids: list[str]
```

## 6.11 Living thesis ledger

A thesis is not a one-off report.

```python
class InvestmentThesis(BaseModel):
    thesis_id: str
    entity_id: str
    created_at: datetime
    horizon_days: int
    status: Literal[
        "draft",
        "active",
        "strengthened",
        "weakened",
        "invalidated",
        "resolved",
        "archived",
    ]
    core_claims: list[ClaimRef]
    valuation_case_ids: list[str]
    catalysts: list[Catalyst]
    risks: list[Risk]
    invalidation_conditions: list[Condition]
    checkpoints: list[ThesisCheckpoint]
    evidence_ids: list[str]
    version: int
```

Each new filing/event can update the thesis, but the prior version remains immutable.

## 6.12 Fundamental research dossier

The human-facing report includes:

1. Executive decision summary  
2. Business model and segments  
3. Industry and competitive position  
4. Historical financial quality  
5. Growth and operating drivers  
6. Accounting quality  
7. Balance sheet and liquidity  
8. Capital allocation  
9. Management and guidance credibility  
10. Operating forecasts  
11. DCF  
12. Reverse DCF / implied expectations  
13. Comparable valuation  
14. Scenario valuation  
15. Catalysts  
16. Risks  
17. Thesis and invalidation conditions  
18. Forecast and uncertainty  
19. Evidence index and calculation lineage  
20. Known gaps  

## 6.13 Backtestable fundamental forecast

The long-form dossier is not directly a portfolio signal.

Create:

```python
class FundamentalScorecard(BaseModel):
    quality: float
    growth: float
    profitability: float
    balance_sheet: float
    cash_conversion: float
    capital_allocation: float
    accounting_quality: float
    valuation: float
    expectations_gap: float
    management_credibility: float
    catalyst: float
    uncertainty: float
```

Then:

```python
class AlphaForecast(BaseModel):
    model_name: str
    symbol: str
    as_of: datetime
    horizon_days: int
    expected_excess_return: float | None
    expected_volatility: float | None
    probability_positive: float
    confidence: float
    uncertainty: float
    thesis: str
    evidence_ids: list[str]
    invalidation_conditions: list[str]
    components: dict[str, float]
    abstained: bool
    abstain_reason: str | None
```

The fundamental model’s forecast must be calibratable and backtestable independently of the prose.

---

# 7. Quantitative Research Engine

## 7.1 Universe engine

The fund mandate is not the watchlist.

Create point-in-time universe snapshots containing:

- symbol membership;
- listing status;
- market cap;
- liquidity;
- sector/industry;
- corporate-action status;
- data completeness;
- borrow eligibility where applicable.

Initial release may use a fixed supplied universe, but the limitation must be explicit.

## 7.2 Factor registry

Factor families:

- value;
- quality;
- profitability;
- investment;
- momentum;
- reversal;
- volatility;
- liquidity;
- earnings revisions;
- PEAD;
- behavioral attention;
- expectations gap;
- graph/relationship risk.

Every factor has:

- economic rationale;
- formula;
- lookback;
- lag;
- universe;
- neutralisation;
- holding horizon;
- cost assumptions;
- evaluation history;
- version.

## 7.3 Factor diagnostics

Run:

- IC and rank IC;
- ICIR;
- quantile returns;
- long-short spread;
- monotonicity;
- turnover;
- factor autocorrelation;
- sector and size neutrality;
- subperiod stability;
- regime performance;
- cost-adjusted returns;
- capacity proxy;
- correlation with existing factors;
- decay monitoring.

## 7.4 Event studies

Integrate:

- market-model abnormal returns;
- CAR windows;
- filing/event types;
- bootstrap confidence intervals;
- source-type segmentation;
- event surprise;
- pre-event leakage checks.

Events:

- earnings;
- guidance;
- buybacks;
- management changes;
- acquisitions;
- legal/regulatory decisions;
- product launches.

## 7.5 Regime engine

At minimum:

- volatility regime;
- market trend;
- rates/liquidity context;
- risk-on/risk-off;
- factor leadership;
- correlation regime.

Use deterministic models first. An LLM may interpret the output but not assign the regime without model evidence.

## 7.6 Behavioral and graph features

Behavioral:

- attention shock;
- mention acceleration;
- sentiment dispersion;
- source diversity;
- narrative saturation;
- abnormal volume;
- price/attention reflexivity.

Graph:

- supplier/customer concentration;
- common ownership;
- sector contagion;
- management/board relationships;
- narrative propagation;
- portfolio common-exposure clusters.

## 7.7 Portfolio model selection

Use a `PortfolioModel` protocol.

Candidates:

- equal weight;
- inverse volatility;
- conviction/forecast weighted;
- mean-risk with shrinkage;
- risk budgeting;
- hierarchical risk parity;
- maximum diversification;
- benchmark tracking;
- robust CVaR where justified.

Use skfolio or an equivalent well-tested library for model selection and cross-validation, while retaining simple fallbacks.

The selected portfolio model is versioned and evaluated, not chosen by an LLM.

---

# 8. Multi-Strategy Fund Architecture

## 8.1 Hierarchy

```text
FUND
    ├─ Fundamental Quality / Expectations Pod
    ├─ Earnings & Event Pod
    ├─ Systematic Factor Pod
    └─ Regime / Defensive Overlay Pod
```

Each pod contains:

```text
alpha models
→ forecast blender
→ pod portfolio policy
→ pod risk budget
```

The fund contains:

```text
pod allocator
→ netting
→ master portfolio model
→ master risk
→ book
```

## 8.2 Suggested first fund

```yaml
name: aegis-institutional-demo

strategies:
  - name: fundamental-expectations
    capital_weight: 0.45
    models:
      - fundamental-scorecard
      - expectations-gap
      - management-credibility
    portfolio_model: forecast_inverse_vol

  - name: earnings-events
    capital_weight: 0.25
    models:
      - pead
      - event-surprise
      - behavioral-reaction
    portfolio_model: forecast_inverse_vol

  - name: systematic-quality-momentum
    capital_weight: 0.20
    models:
      - quality
      - momentum
      - low-volatility
    portfolio_model: risk_budgeting

  - name: defensive-overlay
    capital_weight: 0.10
    models:
      - regime
      - drawdown-control
    portfolio_model: defensive_overlay

master_risk:
  max_position_pct: 0.10
  max_sector_pct: 0.30
  max_gross_exposure: 0.90
  min_cash_pct: 0.10
  max_turnover_pct: 0.25
  allow_shorting: false
  allow_leverage: false
```

## 8.3 Forecast blending

Do not average raw prose confidence.

Blend using:

- expected return;
- forecast uncertainty;
- historical model calibration;
- horizon compatibility;
- feature overlap;
- regime performance;
- evidence quality.

Record each contribution.

## 8.4 Allocator

Initial allocator:

- static capital weights;
- optional inverse-vol strategy scaling;
- pod drawdown caps.

Later candidate allocators:

- risk parity across pods;
- performance-aware but heavily regularised allocator;
- regime-conditioned allocator.

An LLM CIO may explain or propose allocation changes, but deterministic policy decides the weights.

---

# 9. Source Intelligence, Scraping, and Research Memory

Preserve the v2 raw-first and evidence-audit architecture.

## 9.1 Source acquisition ladder

```text
canonical local data
→ official/licensed API
→ regulator/filing feed
→ official company web/RSS
→ direct HTTP
→ Agent Reach channel
→ Scrapling static
→ Scrapling dynamic
→ human review
```

## 9.2 Agent Reach

Use narrow adapters for:

- Reddit;
- YouTube transcripts;
- GitHub;
- RSS;
- optional X/Twitter.

Behavioral sources support attention/flow conclusions, not authoritative fundamentals.

## 9.3 Scrapling

Use controlled static and dynamic worker profiles with:

- domain allowlists;
- page/depth/time limits;
- resource restrictions;
- no broker or ledger credentials;
- raw-first capture;
- source policy;
- historical/current classification.

## 9.4 GBrain

GBrain stores approved:

- company research pages;
- thesis versions;
- management history;
- industry knowledge;
- source quirks;
- post-mortems;
- regime lessons;
- actor profiles;
- skill references;
- contradictions.

It does not store authoritative:

- positions;
- orders;
- cash;
- fills;
- risk limits;
- P&L;
- numerical feature arrays.

## 9.5 Research retrieval score

Combine:

- semantic relevance;
- same entity;
- same industry;
- event type;
- thesis type;
- strategy;
- regime;
- horizon;
- graph proximity;
- evidence quality;
- utility;
- staleness;
- contradiction penalty.

---

# 10. Fund Operations

Paper mode remains included.

Implement:

- carried positions/cash/NAV;
- deterministic paper broker;
- order states;
- transaction costs and slippage;
- exchange calendar;
- idempotent scheduled cycles;
- restart recovery;
- reconciliation;
- book and NAV dashboard.

Paper operation demonstrates deployment parity. It is not the system’s primary intellectual contribution.

---

# 11. Governed Improvement

## 11.1 Improvement candidates

Allowed:

- memory;
- skill;
- prompt;
- model route;
- retrieval policy;
- factor;
- fundamental metric;
- valuation assumption policy;
- alpha model;
- strategy;
- allocator.

Disallowed autonomous candidates:

- risk-policy relaxation;
- broker permissions;
- holdout modification;
- ledger changes;
- evaluation-threshold reduction.

## 11.2 Outcome attribution

Separate:

- thesis quality;
- fundamental forecast;
- valuation error;
- factor/beta contribution;
- timing;
- sizing;
- transaction cost;
- risk intervention;
- unexpected event.

## 11.3 Validation

Candidates must pass as applicable:

- schema/static checks;
- qtype;
- unit tests;
- replay;
- historical PIT tests;
- development period;
- holdback;
- walk-forward;
- purged CV;
- CPCV;
- PBO;
- PSR/DSR;
- cost stress;
- parameter perturbation;
- baseline/ablation comparison;
- shadow mode;
- human promotion.

---

# 12. Markdown agent and skill system

## 12.1 Policies

Create or revise:

```text
policies/POINT_IN_TIME.md
policies/EVIDENCE.md
policies/FUNDAMENTAL_ANALYSIS.md
policies/VALUATION.md
policies/FORECASTING.md
policies/SOURCE_ACQUISITION.md
policies/MEMORY_GOVERNANCE.md
policies/STRATEGY_VALIDATION.md
policies/PORTFOLIO_RISK.md
policies/PAPER_TRADING.md
policies/SELF_IMPROVEMENT.md
policies/PROMOTION.md
```

## 12.2 Fundamental agent manifests

```text
agents/fundamental_coordinator/AGENT.md
agents/business_industry/AGENT.md
agents/financial_quality/AGENT.md
agents/accounting_quality/AGENT.md
agents/growth_drivers/AGENT.md
agents/balance_sheet/AGENT.md
agents/capital_allocation/AGENT.md
agents/management_guidance/AGENT.md
agents/valuation/AGENT.md
agents/catalyst_risk/AGENT.md
agents/thesis_committee/AGENT.md
agents/forecast_verifier/AGENT.md
```

## 12.3 Fundamental skills

```text
skills/filing-ingestion/SKILL.md
skills/statement-normalisation/SKILL.md
skills/company-archetype-routing/SKILL.md
skills/business-model-analysis/SKILL.md
skills/industry-competitive-analysis/SKILL.md
skills/financial-quality/SKILL.md
skills/accounting-quality/SKILL.md
skills/growth-driver-modelling/SKILL.md
skills/management-guidance-tracking/SKILL.md
skills/capital-allocation-analysis/SKILL.md
skills/operating-forecast/SKILL.md
skills/dcf-valuation/SKILL.md
skills/reverse-dcf/SKILL.md
skills/comparable-valuation/SKILL.md
skills/sotp-valuation/SKILL.md
skills/scenario-analysis/SKILL.md
skills/thesis-construction/SKILL.md
skills/thesis-update/SKILL.md
skills/fundamental-forecast-calibration/SKILL.md
skills/fundamental-dossier/SKILL.md
```

Each skill contains:

- objective;
- non-goals;
- triggers;
- supported archetypes;
- typed inputs/outputs;
- allowed tools;
- deterministic calculations;
- PIT rules;
- evidence contract;
- assumptions;
- abstention/halt conditions;
- verification;
- failure modes;
- evaluation fixtures;
- version.

Markdown defines procedure. Tested Python performs financial calculations.

## 12.4 Optional philosophy lenses

Investor-style lenses such as Buffett, Graham, or Druckenmiller may be offered after the core dossier:

```text
“Review this verified dossier through a long-term quality lens.”
```

They may highlight questions or contradictions. They do not become independent alpha models by default.

---

# 13. New domain contracts

At minimum:

```text
CompanyResearchRequest
CompanyArchetype
FilingFact
RawFilingSnapshot
NormalizedFinancialStatements
NormalizationAdjustment
FundamentalMetrics
BusinessModelAssessment
IndustryAssessment
AccountingQualityAssessment
ManagementTrackRecord
OperatingForecast
ValuationAssumption
DCFResult
ImpliedExpectations
ComparableValuation
SOTPResult
ScenarioValuation
FundamentalScorecard
InvestmentThesis
FundamentalResearchDossier
AlphaForecast
StrategyPod
FundMandate
TargetPortfolio
RiskDecision
FundBook
ForecastOutcome
LearningCandidate
PromotionDecision
```

All types are versioned and serialisable.

---

# 14. User interface

## Research Dossier

- company overview;
- evidence timeline;
- segments and industry;
- financial history;
- quality and accounting;
- forecasts;
- DCF;
- reverse DCF;
- comps;
- scenario values;
- management record;
- catalysts and risks;
- thesis;
- forecast;
- gaps.

## Valuation Lab

Interactive assumptions:

- growth;
- margins;
- reinvestment/ROIC;
- discount rate;
- terminal growth;
- scenario probabilities.

Show:

- valuation range;
- reverse-DCF requirements;
- sensitivity;
- implied return.

## Quant Lab

- factor diagnostics;
- event studies;
- regime;
- strategy backtests;
- purged/CPCV;
- portfolio-model comparison;
- baselines and ablations.

## Fund

- strategy sleeves;
- pod contributions;
- target and final weights;
- risk;
- book;
- NAV;
- costs;
- paper cycles.

## Thesis & Memory

- active theses;
- changes over time;
- contradictions;
- checkpoints;
- outcomes;
- lessons.

## Improvement

- candidate diffs;
- experiments;
- holdback;
- shadow results;
- promotion/rollback.

---

# 15. CLI surface

```text
aegisquant research company
aegisquant research update
aegisquant research dossier
aegisquant valuation dcf
aegisquant valuation reverse-dcf
aegisquant valuation comps
aegisquant screen run
aegisquant factors evaluate
aegisquant events study
aegisquant regimes show
aegisquant strategy evaluate
aegisquant fund backtest
aegisquant fund run
aegisquant paper start
aegisquant paper status
aegisquant thesis list
aegisquant thesis show
aegisquant thesis update
aegisquant memory search
aegisquant learn outcomes
aegisquant learn dream
aegisquant promotions review
```

Follow the existing CLI structure after repository inspection.

---

# 16. Dependency adoption matrix

| Component | Decision | Reason |
|---|---|---|
| Existing v2 run-cycle/backtest | Keep | Audited and deterministic |
| LangGraph | Keep | Research workflow and replay |
| Pydantic v2 | Keep | Typed artifacts |
| SQLite tamper-evident ledgers | Keep | Local-first authoritative state |
| Polars/Pandas/NumPy/SciPy | Keep | Numerical foundation |
| statsmodels | Adopt if absent | regressions, event studies, diagnostics |
| `implied-expectations` | Evaluate dependency or adapt methodology | reverse DCF and XBRL lineage |
| skfolio | Adopt behind adapter if compatible | robust portfolio models and validation |
| purgedcv | Adopt/keep | honest financial validation |
| qtype | Dev/evaluation dependency | obvious static leakage checks |
| Alphalens-reloaded | Evaluate | factor diagnostics; do not duplicate if existing tools suffice |
| VectorBT | Optional | fast large parameter sweeps |
| QuantStats/ffn | Optional | reports |
| exchange_calendars | Adopt | market-session correctness |
| FinancePy/rateslib | Defer | no fixed-income scope |
| PyMC | Defer | Bayesian valuation is not release critical |
| GBrain | Optional adapter | research memory only |
| Agent Reach/Scrapling | Controlled adapters | source intelligence |
| Temporal/Kafka/Kubernetes | Defer | unnecessary for local-first v3 |

Every adopted dependency requires:

- licence review;
- pinned version;
- adapter boundary;
- tests;
- fallback or clear failure behavior.

---

# 17. Test strategy

## Fundamental tests

- XBRL mapping and lineage;
- filing-date eligibility;
- restatement handling;
- statement reconciliation;
- share-count dilution;
- one-time adjustment preservation;
- ROIC/reinvestment identities;
- forecast statement arithmetic;
- scenario ordering;
- DCF closed-form/golden cases;
- DCF round-trip tests;
- reverse-DCF inversion recovery;
- sensitivity monotonicity;
- unsupported-sector abstention;
- exact numerical citation requirements.

## Research graph tests

- agent tool authority;
- specialist fan-out/fan-in;
- evidence-audit blocking;
- no new facts in thesis committee;
- future evidence/memory exclusion;
- prompt-injection quarantine;
- replay determinism.

## Quant tests

- factor lag;
- universe PIT;
- IC and quantile calculations;
- event CARs;
- purging/embargo;
- PBO/DSR;
- portfolio constraints;
- skfolio adapter equivalence/fallback;
- baseline comparisons.

## Fund tests

- target sleeve netting;
- risk monotonicity;
- cash/NAV conservation;
- duplicate-cycle prevention;
- restart recovery;
- cost accounting;
- no agent order authority.

## Learning tests

- every experiment recorded;
- no candidate auto-activation;
- proposer cannot approve;
- shadow output cannot affect weights;
- rollback restores champion;
- lucky outcome classification does not automatically create an active global lesson.

## Golden research cases

Ship frozen evidence and expected calculations for at least:

1. profitable high-quality compounder;
2. overvalued high-growth company;
3. deteriorating cyclical;
4. bank/financial unsupported or sector-specific path;
5. accounting-quality warning case;
6. guidance-credibility deterioration;
7. acquisition-heavy capital-allocation case;
8. all-agents-abstain case.

---

# 18. Milestones and gates

## Milestone 1 — Fundamental data and normalisation

**Gate:** statements reconcile and every normalised number has lineage.

## Milestone 2 — Deterministic metrics and archetype router

**Gate:** general-company metrics are correct; unsupported archetypes abstain.

## Milestone 3 — Forecast and valuation engines

**Gate:** DCF/reverse DCF pass round-trip and sensitivity tests.

## Milestone 4 — Fundamental research graph

**Gate:** full dossier and verified forecast on frozen cases.

## Milestone 5 — Thesis ledger and management tracking

**Gate:** quarterly update preserves versions and recalculates guidance accuracy.

## Milestone 6 — Screening and factor diagnostics

**Gate:** universe ranking is PIT and benchmarked.

## Milestone 7 — Portfolio-model framework

**Gate:** simple and skfolio-backed models compare through one interface.

## Milestone 8 — Multi-strategy fund

**Gate:** pods net into one target book with attributed contributions.

## Milestone 9 — Paper and monitoring mode

**Gate:** persistent cycles, source events, and reconciliation work.

## Milestone 10 — Memory and governed learning

**Gate:** candidate evaluation, shadow, promotion, and rollback are complete.

---

# 19. Final acceptance criteria

AegisQuant v3 is complete when:

1. It can research a company independently of fund execution.
2. The dossier contains deterministic financial calculations and complete evidence lineage.
3. DCF and reverse DCF expose assumptions, ranges, and sensitivities.
4. Fundamental agents reason from verified calculations rather than inventing metrics.
5. Investor personas are optional lenses, not portfolio voters by default.
6. Fundamental output is converted into a calibrated backtestable forecast.
7. The quant engine evaluates factors, events, regimes, and portfolio models.
8. Simple portfolio baselines remain visible and competitive.
9. Multi-strategy pods net into one deterministic fund book.
10. Replay, backtest, current research, and paper modes remain coherent.
11. Historical cases exclude future evidence and memory.
12. Every candidate research change is recorded and evaluated.
13. No candidate self-promotes.
14. All v2 and v3 static, unit, integration, adversarial, replay, and property tests pass.
15. Two isolated replay runs are byte-identical.
16. The worktree is clean and documentation matches behavior.

---

# 20. CV-ready positioning

After implementation:

- **Built AegisQuant, an evidence-first institutional investment operating system combining hierarchical LangGraph research, point-in-time filing/XBRL analysis, driver-based forecasting, DCF and reverse-DCF valuation, factor/event research, robust portfolio optimisation, deterministic risk, and replayable backtest/paper fund modes.**
- **Designed a multi-strategy fund architecture in which fundamental, event, systematic, behavioral, and regime alpha models emit calibrated forecasts into independently tested portfolio policies and a hard-risk master book.**
- **Implemented living investment-thesis and management-credibility ledgers, raw-first Agent Reach/Scrapling source acquisition, GBrain-backed approved memory, and human-gated champion–challenger improvement with purged/CPCV/PBO/DSR validation.**

---

# 21. Explicit non-goals

Do not add in v3:

- live-money broker;
- autonomous promotion;
- HFT;
- intraday market making;
- options or fixed-income portfolios;
- all global markets;
- a custom graph database;
- Kubernetes/Kafka/Temporal;
- unconstrained arbitrary-code agents;
- a persona-voting investment committee;
- unsupported “fair value” precision;
- a full institutional accounting system.

The correct upgrade is a deep research, valuation, quant, portfolio, and paper-fund OS—not an unfinished everything-platform.
