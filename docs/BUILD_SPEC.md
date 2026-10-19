# AegisQuant MVP v2 — Capability-Complete Design Specification

## 0. Executive decision

AegisQuant v2 remains a **paper-trading and research MVP**, but it is upgraded from a basic multi-agent stock analyst into a compact investment-research operating system with:

- a real fund hierarchy and one reproducible `run_cycle` path;
- a hierarchical LangGraph research desk;
- Markdown-defined agents, skills, policies, and research programs;
- point-in-time financial snapshots and evidence provenance;
- controlled internet research through Agent Reach and Scrapling;
- hybrid and graph-aware long-term memory through GBrain;
- behavioral, event, fundamental, and quantitative specialist analysis;
- deterministic portfolio construction, hard risk, and simulated execution;
- a complete experiment and outcome ledger;
- governed skill, prompt, routing, memory, and strategy improvement;
- replay mode that works without API keys.

The system is intentionally **not** a live trading bot. It must demonstrate the full research-to-paper-portfolio lifecycle reliably before any live broker is considered.

The implementation principle is:

> Agents investigate, interpret, challenge, and propose. Typed and deterministic components validate, calculate, size, constrain, execute, and promote.

---

## 1. Recommended architectural approach

Three approaches were considered.

### Approach A — Extend the existing MVP minimally

Add Agent Reach, Scrapling, and GBrain as loose tools around the existing graph.

**Advantages**

- fastest initial integration;
- fewer new abstractions.

**Weaknesses**

- web results enter agent context inconsistently;
- memory can become polluted;
- hard to replay and audit;
- self-improvement becomes prompt-driven rather than evidence-driven.

### Approach B — Capability-rich modular monolith — recommended

Keep one Python application and one LangGraph runtime, but create explicit internal subsystems:

1. Source Intelligence;
2. Evidence and Retrieval;
3. Memory and Knowledge;
4. Agent Research;
5. Quant and Fund Engine;
6. Learning and Promotion.

All modules communicate through Pydantic contracts and share SQLite/DuckDB/local object storage in the MVP.

**Advantages**

- serious capabilities without microservice overhead;
- deterministic replay remains possible;
- clear security and ownership boundaries;
- easiest architecture to explain on a CV;
- modules can later be extracted into services.

### Approach C — Distributed production platform

Separate crawler, memory, retrieval, agents, quant, risk, execution, and learning into services.

**Advantages**

- independent scaling and isolation.

**Weaknesses**

- infrastructure-heavy;
- not required for a research/paper MVP;
- would reduce delivery quality.

**Decision:** build Approach B.

---

## 2. Foundation and benchmark synthesis

### Base quantitative engine

Start from a pinned fork of `virattt/ai-hedge-fund` v2 at commit:

```text
eff8a7320fcf0b473b135690fa1a5b0d9b022a83
```

Preserve and extend:

- Fund → Strategy → AlphaModel hierarchy;
- YAML fund mandates;
- point-in-time `DataClient` protocol;
- `run_cycle` as the one fund-cycle path;
- simulated broker;
- deterministic portfolio/risk/execution stages;
- backtest using the same cycle;
- persistent cycle receipts.

### Agent design inspiration

Use lessons from:

- **TradingAgents:** specialist decomposition, independent bull/bear reasoning, structured state;
- **AI Hedge Fund:** fund as a first-class object, alpha-model interface, one engine across modes, deterministic risk;
- **Alpha Skills:** Markdown-first quant procedures and progressive specialist skills;
- **AutoHypothesis:** locked evaluation core, editable candidate surface, hypothesis declaration, holdback and walk-forward gates;
- **Prime Agent:** persistent research workbench, bounded subagents, versioned refinement ideas;
- **Hermes Agent:** skill packaging, prompt layering, memory/skill write approval, progressive disclosure;
- **Agent Reach:** specialised channel discovery and access;
- **Scrapling:** resilient static/dynamic crawling and adaptive extraction;
- **GBrain:** hybrid retrieval, synthesis, entity links, gap analysis, consolidation cycles;
- **purgedcv/qtype:** leakage-aware validation and static quant checks.

### Original contribution

AegisQuant's original value is not the imported fund engine. It is the **finance-specific harness** that joins:

```text
point-in-time evidence
+ skill-defined specialist agents
+ governed web acquisition
+ graph-aware memory
+ forecast verification
+ honest quantitative evaluation
+ deterministic paper portfolio mechanics
+ staged self-improvement
```

---

## 3. Non-negotiable invariants

1. No LLM can place an order or modify the broker ledger.
2. No LLM can alter hard risk limits during a run.
3. Historical runs cannot use live-only sources or future memories.
4. Every material factual claim must reference an `evidence_id`.
5. Every historical evidence item must satisfy `available_at <= case.as_of`.
6. Exact numeric claims must point to a structured field, table cell, or deterministic calculation.
7. Web content is untrusted data and can never become instruction.
8. LLM failures produce abstention; data-integrity failures halt.
9. Every attempted strategy and parameter variation is logged.
10. A profitable result is not automatically a correct thesis.
11. The author of a skill or strategy candidate cannot approve it.
12. Self-improvement produces candidates; promotion is separately evaluated and approved.
13. The same portfolio/risk/simulated execution path runs in historical and paper modes.
14. Uncertain side effects are never blindly replayed.
15. The project must ship with a deterministic no-key replay demo.

---

## 4. Product modes

### 4.1 Replay mode

Purpose: reliable demonstration, CI, and recruiter evaluation.

- fixture market/fundamental/news data;
- cached evidence pages;
- cached model outputs;
- local deterministic memory backend;
- no network;
- byte-stable case artifacts where possible.

### 4.2 Historical research mode

Purpose: honest backtests and historical case reconstruction.

- point-in-time structured data only;
- historical archived evidence only;
- memory filtered by `available_at`;
- Agent Reach disabled unless the connector provides a dated archive;
- Scrapling disabled by default;
- fixed prompts, skills, models, and data snapshots recorded in the manifest.

### 4.3 Live research mode

Purpose: current investment research and paper portfolio recommendations.

- current market data;
- official sources;
- Agent Reach channels;
- Scrapling and browser fallback;
- GBrain current memory;
- simulated broker only.

### 4.4 Research-lab mode

Purpose: candidate factor, strategy, skill, and routing experiments.

- sandboxed code execution;
- development/holdback/walk-forward/locked-holdout splits;
- complete experiment ledger;
- no production promotion without approval.

---

## 5. High-level system architecture

```text
User / Scheduler
      ↓
Case Intake
      ↓
Point-in-Time Snapshot + Memory Recall
      ↓
Research Coordinator
      ↓
Specialist Fan-Out
  ├─ Quant
  ├─ Fundamentals
  ├─ Event & Behavioral
  └─ Relationship / Portfolio Context when required
      ↓
Evidence Auditor
      ↓
Independent Bull + Bear + Base-Rate Review
      ↓
CIO Forecast Synthesis
      ↓
Forecast Verifier
      ↓
Deterministic Portfolio Constructor
      ↓
Hard Risk Policy
      ↓
Simulated Broker + Ledger
      ↓
Backtest / Outcome Attribution
      ↓
Memory + Skill + Strategy Improvement Candidates
      ↓
Evaluation / Shadow / Human Promotion
```

---

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
│   ├── dashboard.py
│   └── scheduler.py
│
├── aegis/
│   ├── contracts/
│   │   ├── case.py
│   │   ├── source.py
│   │   ├── evidence.py
│   │   ├── claims.py
│   │   ├── memory.py
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
│   │   ├── coordinator.py
│   │   ├── context_compiler.py
│   │   ├── skill_loader.py
│   │   ├── model_router.py
│   │   ├── capability_broker.py
│   │   ├── checkpoints.py
│   │   └── budgets.py
│   │
│   ├── agents/
│   │   ├── coordinator/
│   │   │   └── AGENT.md
│   │   ├── quant/
│   │   │   └── AGENT.md
│   │   ├── fundamentals/
│   │   │   └── AGENT.md
│   │   ├── event_behavioral/
│   │   │   └── AGENT.md
│   │   ├── relationship/
│   │   │   └── AGENT.md
│   │   ├── portfolio_context/
│   │   │   └── AGENT.md
│   │   ├── evidence_auditor/
│   │   │   └── AGENT.md
│   │   ├── bull/
│   │   │   └── AGENT.md
│   │   ├── bear/
│   │   │   └── AGENT.md
│   │   ├── cio/
│   │   │   └── AGENT.md
│   │   ├── verifier/
│   │   │   └── AGENT.md
│   │   └── postmortem/
│   │       └── AGENT.md
│   │
│   ├── sources/
│   │   ├── registry.py
│   │   ├── gateway.py
│   │   ├── planner.py
│   │   ├── direct_http.py
│   │   ├── rss.py
│   │   ├── official_apis.py
│   │   ├── agent_reach.py
│   │   ├── scrapling_worker.py
│   │   ├── browser_worker.py
│   │   ├── health.py
│   │   ├── rate_limits.py
│   │   └── watchers.py
│   │
│   ├── ingestion/
│   │   ├── raw_store.py
│   │   ├── normalize.py
│   │   ├── html.py
│   │   ├── pdf.py
│   │   ├── xbrl.py
│   │   ├── tables.py
│   │   ├── entities.py
│   │   ├── dedupe.py
│   │   ├── timestamps.py
│   │   └── injection_scan.py
│   │
│   ├── evidence/
│   │   ├── ledger.py
│   │   ├── claim_graph.py
│   │   ├── numeric_claims.py
│   │   ├── validators.py
│   │   ├── contradictions.py
│   │   └── context_pack.py
│   │
│   ├── retrieval/
│   │   ├── query_compiler.py
│   │   ├── lexical.py
│   │   ├── vector.py
│   │   ├── graph_expand.py
│   │   ├── rerank.py
│   │   └── packer.py
│   │
│   ├── memory/
│   │   ├── protocol.py
│   │   ├── local_backend.py
│   │   ├── gbrain_backend.py
│   │   ├── governance.py
│   │   ├── candidates.py
│   │   ├── retrieval.py
│   │   ├── consolidation.py
│   │   ├── dream_cycle.py
│   │   └── utility.py
│   │
│   ├── graph/
│   │   ├── relations.py
│   │   ├── projections.py
│   │   ├── evidence_graph.py
│   │   ├── company_graph.py
│   │   ├── narrative_graph.py
│   │   └── skill_graph.py
│   │
│   ├── fund/
│   │   ├── spec.py
│   │   ├── models.py
│   │   ├── run_cycle.py
│   │   ├── ledger.py
│   │   ├── broker.py
│   │   └── allocator.py
│   │
│   ├── quant/
│   │   ├── snapshots.py
│   │   ├── factors.py
│   │   ├── pead.py
│   │   ├── regime.py
│   │   ├── behavioral.py
│   │   ├── graph_features.py
│   │   ├── calibration.py
│   │   ├── portfolio.py
│   │   ├── costs.py
│   │   └── metrics.py
│   │
│   ├── risk/
│   │   ├── policy.py
│   │   ├── checks.py
│   │   ├── stress.py
│   │   └── signatures.py
│   │
│   ├── research_lab/
│   │   ├── program.md
│   │   ├── runner.py
│   │   ├── experiments.py
│   │   ├── validation.py
│   │   ├── shadow.py
│   │   └── promotion.py
│   │
│   └── observability/
│       ├── events.py
│       ├── traces.py
│       ├── metrics.py
│       └── manifests.py
│
├── policies/
│   ├── EVIDENCE_POLICY.md
│   ├── POINT_IN_TIME_POLICY.md
│   ├── SOURCE_POLICY.md
│   ├── MEMORY_POLICY.md
│   ├── SELF_IMPROVEMENT_POLICY.md
│   ├── MODEL_ROUTING_POLICY.md
│   ├── RISK_POLICY.md
│   └── SECURITY_POLICY.md
│
├── skills/
│   ├── research/
│   ├── sources/
│   ├── evidence/
│   ├── quant/
│   ├── memory/
│   ├── review/
│   └── learning/
│
├── configs/
│   ├── funds/
│   ├── sources/
│   ├── models/
│   └── demo/
│
├── data/
│   ├── fixtures/
│   ├── lake/raw/
│   ├── lake/normalized/
│   ├── parquet/
│   └── databases/
│
└── tests/
    ├── unit/
    ├── integration/
    ├── replay/
    ├── scraping/
    ├── memory/
    ├── security/
    ├── quant/
    └── acceptance/
```

---

## 7. Source Intelligence and scraping subsystem

### 7.1 Purpose

The scraping system is not an unrestricted browser tool. It is a **source acquisition pipeline** that decides:

- which source is appropriate;
- whether it may be used in the current mode;
- how to acquire it;
- how to preserve it;
- how to validate it;
- how to turn it into evidence.

### 7.2 Source registry

Each source has a versioned manifest.

```python
class SourceManifest(BaseModel):
    source_id: str
    display_name: str
    source_type: Literal[
        "official_api",
        "licensed_api",
        "official_web",
        "rss",
        "social",
        "community",
        "crawler",
    ]

    domains: list[str]
    markets: list[str]
    information_types: list[str]

    live_safe: bool
    historical_safe: bool
    point_in_time_safe: bool

    requires_auth: bool
    credential_scope: str | None
    licence_classification: str

    obey_robots: bool
    minimum_interval_seconds: int
    max_pages_per_job: int
    max_depth: int

    retention_policy: str
    parser_profile: str
    reliability_prior: float
```

Example source categories:

```text
sec-edgar
company-ir
fred
exchange-filings
rss-company-news
agent-reach-reddit
agent-reach-x
agent-reach-youtube
agent-reach-github
scrapling-approved-web
manual-upload
```

### 7.3 Acquisition hierarchy

```text
Canonical local snapshot
→ official/licensed API
→ official HTML/RSS
→ direct HTTP + clean extraction
→ Agent Reach specialised channel
→ Scrapling static fetch
→ Scrapling dynamic fetch
→ isolated browser worker
→ human/manual upload
```

The first acceptable source wins unless the research plan explicitly requires corroboration.

### 7.4 Source planner

Agents request information, not tools.

```python
class SourceRequest(BaseModel):
    case_id: str
    entity_ids: list[str]
    information_type: str
    query: str
    as_of: datetime
    mode: Literal["replay", "historical", "live"]
    freshness: timedelta | None
    corroboration_required: bool
    max_sources: int
    max_cost_usd: float
```

The `SourcePlanner` chooses source manifests and an acquisition method.

### 7.5 Agent Reach integration

Agent Reach is wrapped behind narrow adapters:

```python
search_reddit(query, communities, start, end)
search_x(query, accounts, start, end)
get_youtube_transcript(video_id)
search_github_activity(org, repo, start, end)
read_rss(feed_id, since)
```

Rules:

- the model never executes arbitrary Agent Reach commands;
- each channel has an explicit credential scope;
- raw results are stored before summarisation;
- the actual backend and connector version are logged;
- current/live social results are prohibited in historical mode;
- cookie-authenticated channels use dedicated research accounts;
- connector health is checked through a scheduled `doctor` job.

### 7.6 Scrapling integration

Use two Scrapling execution profiles.

#### Static profile

- HTML pages that do not require browser rendering;
- runs in a restricted Python worker;
- low resource limits;
- preferred for official pages and tables.

#### Dynamic profile

- JavaScript-heavy pages;
- adaptive selectors;
- XHR interception when approved;
- separate subprocess/container;
- strict domain allowlist;
- browser memory/time limits;
- no access to database or broker secrets.

```python
class ScrapeJob(BaseModel):
    job_id: str
    source_id: str
    url: str
    purpose: str
    extraction_schema: str
    mode: Literal["static", "dynamic"]
    as_of: datetime
    domain_allowlist: list[str]
    maximum_pages: int
    maximum_depth: int
    timeout_seconds: int
```

### 7.7 Watchers and scheduled monitoring

The MVP should support scheduled source watchers for a small portfolio/watchlist.

Watch types:

- new regulatory filing;
- earnings date or transcript;
- company IR page change;
- RSS/news change;
- GitHub release or repository activity;
- social attention spike;
- unusual price/volume event.

A watcher produces an `EventCandidate`, not an automatic trade.

```python
class EventCandidate(BaseModel):
    event_id: str
    entity_ids: list[str]
    detected_at: datetime
    event_type: str
    source_evidence_ids: list[str]
    novelty_score: float
    urgency_score: float
    requires_case: bool
```

### 7.8 Incremental crawling and change detection

For monitored pages, store:

- `ETag`;
- `Last-Modified`;
- response hash;
- normalized content hash;
- DOM fingerprint;
- last successful extraction schema;
- previous structured result.

Only changed content is re-processed.

### 7.9 Source health

Track per source:

- success rate;
- median latency;
- stale-data frequency;
- parser failure rate;
- CAPTCHA/block rate;
- citation usefulness;
- contradiction rate;
- recent health status.

The source planner uses health as one input, not as proof of factual reliability.

---

## 8. Ingestion and document intelligence

### 8.1 Immutable raw capture

Every fetched item is content-addressed.

```text
data/lake/raw/<sha256-prefix>/<sha256>.<extension>
```

Store:

- body bytes;
- headers;
- status;
- URL;
- fetch timestamp;
- connector;
- source manifest version;
- retrieval job ID.

### 8.2 Normalisation pipeline

```text
raw bytes
→ format detection
→ safe parser
→ text/table extraction
→ timestamp normalisation
→ entity resolution
→ duplicate detection
→ section/chunk creation
→ evidence registration
```

Supported MVP formats:

- HTML;
- JSON;
- RSS/Atom;
- PDF text;
- XBRL/XML;
- CSV;
- Markdown/plain text;
- YouTube/social transcripts.

OCR is a last-resort path and should not be part of the default demo.

### 8.3 Timestamp model

Each item records:

```python
class SourceTime(BaseModel):
    event_time: datetime | None
    published_at: datetime | None
    available_at: datetime
    retrieved_at: datetime
    revised_at: datetime | None
```

`available_at` controls historical eligibility.

### 8.4 Entity resolution

Resolve:

- company;
- security/ticker;
- person;
- product;
- sector;
- regulator;
- customer/supplier;
- document type;
- event type.

Each resolution has confidence and evidence. Ambiguous symbols must not be silently mapped.

### 8.5 Deduplication

Use:

- content hash for exact duplicates;
- canonical URL;
- normalized text fingerprint;
- title/time/source similarity;
- near-duplicate embedding similarity.

Syndicated articles may be stored as separate sources but linked to a canonical event cluster.

### 8.6 Injection and malicious-content scan

Flag:

- instructions to the agent;
- credential requests;
- exfiltration attempts;
- hidden Unicode;
- encoded commands;
- suspicious links;
- embedded scripts.

The content remains available as evidence, but flagged blocks are never interpreted as instructions.

---

## 9. Evidence and claim system

### 9.1 Evidence record

```python
class EvidenceRecord(BaseModel):
    evidence_id: str
    source_id: str
    source_url: str | None
    content_hash: str
    raw_uri: str

    entity_ids: list[str]
    document_type: str
    section: str | None
    page: int | None
    coordinates: str | None

    event_time: datetime | None
    published_at: datetime | None
    available_at: datetime
    retrieved_at: datetime

    source_quality: float
    extraction_confidence: float
    historical_safe: bool
    injection_flags: list[str]

    parser_version: str
    extractor_version: str
```

### 9.2 Claim graph

```text
Evidence SUPPORTS Claim
Evidence CONTRADICTS Claim
Claim DERIVED_BY Calculation
Claim USED_IN Artifact
Artifact USED_IN Forecast
Forecast LED_TO PortfolioDecision
PortfolioDecision LED_TO Outcome
```

### 9.3 Numeric claims

```python
class NumericClaim(BaseModel):
    claim_id: str
    name: str
    value: Decimal
    unit: str
    evidence_id: str
    coordinates: str
    calculation_id: str | None
```

An LLM cannot be the source of an exact number.

### 9.4 Evidence audit gates

A case cannot proceed when:

- mandatory evidence is missing;
- a material claim lacks provenance;
- historical eligibility fails;
- an entity match is ambiguous;
- critical sources contradict each other without disclosure;
- evidence is stale beyond policy;
- extraction confidence is below the minimum.

---

## 10. Retrieval and context construction

### 10.1 Query compiler

A natural research request becomes a structured query:

```python
class RetrievalQuery(BaseModel):
    text: str
    entity_ids: list[str]
    document_types: list[str]
    as_of: datetime
    horizon_days: int | None
    strategy_ids: list[str]
    regime_ids: list[str]
    memory_types: list[str]
    top_k: int
```

### 10.2 Retrieval stages

```text
metadata and point-in-time filter
→ lexical retrieval
→ dense retrieval
→ graph expansion
→ reciprocal-rank fusion
→ cross-encoder reranking
→ diversity/deduplication
→ context packing
```

### 10.3 Context pack

Agents receive a bounded `ContextPack` containing:

- case mandate;
- allowed tasks;
- deterministic snapshot;
- relevant memories;
- evidence excerpts;
- missing-data warnings;
- explicit source IDs;
- token/cost budget.

The pack contains no unrestricted session transcript.

### 10.4 Prompt layering

Adopt four layers:

```text
Stable:
agent policy, tool rules, skill metadata

Case:
mandate, as-of date, horizon, task

Evidence:
retrieved point-in-time artifacts and memories

Ephemeral:
retry reason, budget warning, human note
```

---

## 11. Memory system

### 11.1 Backend design

```python
class MemoryBackend(Protocol):
    def search(self, query: MemoryQuery) -> list[MemoryHit]: ...
    def get(self, memory_id: str) -> MemoryItem: ...
    def stage(self, candidate: MemoryCandidate) -> str: ...
    def approve(self, candidate_id: str) -> MemoryItem: ...
```

Implement:

- `LocalMemoryBackend`: SQLite FTS5 + embeddings for replay/CI;
- `GBrainMemoryBackend`: production-like research memory through MCP/CLI/API.

GBrain must be optional so the demo remains runnable without a separate service.

### 11.2 Memory classes

#### Working memory

- current research plan;
- unresolved questions;
- specialist status;
- temporary tool results.

Stored in LangGraph state/checkpoints. Deleted or archived when the case closes.

#### Episodic memory

- complete prior case;
- evidence used;
- disagreements;
- forecast;
- portfolio decision;
- outcome.

#### Semantic memory

- durable company facts;
- source behavior;
- market rules;
- management history;
- stable relationships.

#### Procedural memory

- approved research workflows;
- tool workarounds;
- source-specific procedures;
- skill usage guidance.

#### Regime memory

- lessons conditioned on market state;
- factor behavior by regime;
- event reaction patterns.

#### Negative memory

- known data traps;
- invalidated theses;
- failed skills;
- unreliable sources;
- overfitted factors.

#### Counterfactual memory

- no-trade outcome;
- delayed-entry outcome;
- different sizing outcome;
- no-memory/no-debate ablation outcome.

#### Actor memory

- public statements;
- predictions;
- domain calibration;
- disclosure lag;
- management guidance accuracy;
- influence versus correctness.

### 11.3 Finance schema pack for GBrain

Recommended page/node types:

```text
company
security
person
source
filing
event
claim
thesis
forecast
portfolio-decision
trade-outcome
strategy
factor
regime
skill
failure-mode
lesson
research-case
```

Recommended relations:

```text
supports
contradicts
supersedes
applies_to
failed_in
worked_in
caused_by_hypothesis
uses_skill
uses_model
exposed_to
supplies
competes_with
managed_by
predicted_by
resolved_as
```

### 11.4 Memory candidate pipeline

```text
trajectory/outcome
→ candidate extraction
→ memory classification
→ evidence linkage
→ duplicate search
→ contradiction check
→ scope selection
→ confidence and expiry
→ approval policy
→ authoritative record
→ GBrain projection
```

### 11.5 Memory object

```python
class MemoryItem(BaseModel):
    memory_id: str
    memory_type: str
    title: str
    statement: str

    evidence_ids: list[str]
    source_case_ids: list[str]

    entity_ids: list[str]
    strategy_ids: list[str]
    regime_ids: list[str]

    scope: Literal["case", "entity", "strategy", "project", "global"]
    confidence: float
    utility_score: float

    available_at: datetime
    expires_at: datetime | None
    supersedes: list[str]
    contradicted_by: list[str]

    status: Literal["candidate", "approved", "quarantined", "retired"]
    version: int
```

### 11.6 Retrieval scoring

Memory relevance should combine:

```text
semantic similarity
+ entity match
+ strategy match
+ regime match
+ event-type match
+ horizon match
+ graph proximity
+ evidence quality
+ historical eligibility
+ past retrieval utility
- contradiction penalty
- staleness penalty
```

### 11.7 Dream cycle

Run a scheduled consolidation job after cases/outcomes mature.

Tasks:

1. ingest newly approved case summaries;
2. repair missing citations;
3. link entities and relationships;
4. merge exact and near duplicates;
5. detect contradictions;
6. mark stale memories;
7. calculate utility from retrieval/usefulness feedback;
8. archive low-utility memories;
9. create candidate lessons from repeated failures/successes;
10. produce a human-readable consolidation report.

The dream cycle cannot change risk, execute trades, or promote strategies.

### 11.8 Forgetting and retirement

Memory must be able to forget.

Retire when:

- superseded by newer evidence;
- expired;
- repeatedly contradicted;
- no longer relevant to active markets/strategies;
- low utility after sufficient retrieval opportunities;
- associated source is invalidated.

Never silently delete case/outcome audit history; archive it instead.

---

## 12. Hierarchical agent graph

### 12.1 Adaptive depth

The coordinator chooses the smallest sufficient graph.

```text
L0 Screen:
deterministic quant only

L1 Standard:
Quant + Fundamental + Auditor + CIO + Verifier

L2 Event:
Quant + Fundamental + Event/Behavioral + Auditor + Bull/Bear + CIO + Verifier

L3 Deep:
add Relationship and Portfolio Context; one evidence retry; human review
```

### 12.2 Agent roster

#### Research Coordinator

- decomposes the case;
- selects agents and skills;
- creates budgets;
- cannot produce the final forecast.

#### Quant Analyst

- interprets deterministic factors;
- checks signal robustness;
- distinguishes absolute from cross-sectional views;
- cannot invent indicators.

#### Fundamental Analyst

- business quality;
- profitability and balance sheet;
- valuation;
- management and guidance;
- point-in-time filings only.

#### Event & Behavioral Analyst

- catalyst extraction;
- attention and salience;
- narrative spread;
- investor-segment reaction;
- continuation/overshoot/reversal probabilities;
- manipulation and coordination warnings.

#### Relationship Analyst

- suppliers/customers;
- competitors;
- common ownership;
- regulatory and geographic exposure;
- graph-derived risk paths.

#### Portfolio Context Analyst

- current holdings;
- overlap and correlation;
- factor concentration;
- benchmark context;
- portfolio-specific opportunity cost.

#### Evidence Auditor

- point-in-time gate;
- provenance and source-quality audit;
- contradiction audit;
- numeric claim verification;
- can block the case.

#### Bull Reviewer

- strongest evidence-backed upside case;
- independent first memo.

#### Bear Reviewer

- strongest evidence-backed downside case;
- independent first memo.

#### CIO

- synthesises only approved artifacts;
- produces `AlphaForecast`;
- cannot retrieve new facts.

#### Forecast Verifier

- schema;
- evidence coverage;
- numeric coherence;
- horizon and confidence;
- can force abstention.

#### Postmortem Agent

- reads matured outcomes and deterministic attribution;
- proposes learning candidates;
- cannot apply them.

### 12.3 Debate design

```text
Validated Evidence Bundle
├─ Independent Bull Memo
├─ Independent Bear Memo
└─ Base-Rate Memo
        ↓
Contradiction matrix
        ↓
Optional single rebuttal
        ↓
CIO synthesis
```

No open-ended debate loop in the MVP.

---

## 13. Skills and instructions

### 13.1 File hierarchy

```text
AGENTS.md
  global repo operating rules

HARNESSES.md
  graph states, routing, permissions, completion rules

agents/<role>/AGENT.md
  role, authority, prohibited behavior, outputs

skills/<category>/<skill>/SKILL.md
  reusable procedure

policies/*.md
  non-negotiable safety and financial rules

research_lab/program.md
  candidate improvement protocol
```

### 13.2 Skill format

```yaml
---
name: evidence-first-company-research
version: 1.0.0
owner: research
roles: [fundamental-analyst]
inputs: [CaseContext, FundamentalsSnapshot, EvidenceBundle]
outputs: [FundamentalAssessment]
allowed_tools:
  - data.financial_snapshot
  - evidence.search
  - evidence.numeric_lookup
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
12. Failure modes
13. Memory policy
14. Evaluation cases
15. Version history

### 13.3 Initial capability-complete skill set

#### Research planning

- `case-plan`
- `research-depth-routing`
- `source-plan`

#### Source acquisition

- `official-source-first`
- `agent-reach-channel-search`
- `scrapling-static-extraction`
- `scrapling-dynamic-extraction`
- `source-change-monitoring`

#### Evidence

- `point-in-time-safety`
- `evidence-normalization`
- `numeric-claim-verification`
- `contradiction-audit`
- `prompt-injection-triage`

#### Specialist research

- `quant-signal-analysis`
- `fundamental-quality-valuation`
- `earnings-guidance-analysis`
- `event-behavioral-reaction`
- `relationship-exposure-analysis`
- `portfolio-context-analysis`

#### Review and synthesis

- `bull-case`
- `bear-case`
- `base-rate-analysis`
- `cio-synthesis`
- `forecast-audit`

#### Memory

- `memory-recall`
- `memory-candidate-write`
- `memory-contradiction-review`
- `memory-consolidation`

#### Quant lab

- `factor-discover`
- `factor-evaluate`
- `factor-backtest`
- `strategy-validation`
- `factor-monitor`

#### Learning

- `case-postmortem`
- `candidate-refinement`
- `shadow-evaluation`
- `promotion-review`

---

## 14. Core financial contracts

### 14.1 Alpha forecast

```python
class AlphaForecast(BaseModel):
    forecast_id: str
    model_name: str
    ticker: str
    as_of: datetime
    horizon_days: int

    expected_excess_return: float | None
    expected_volatility: float | None
    probability_positive: float

    confidence: float
    uncertainty: float

    downside_case: float | None
    base_case: float | None
    upside_case: float | None

    thesis: str
    evidence_ids: list[str]
    invalidation_conditions: list[str]
    catalyst_dates: list[datetime]
    thesis_expiry: datetime | None

    abstained: bool
    abstain_reason: str | None
    components: dict[str, float]
    metadata: dict[str, Any]
```

### 14.2 Batch alpha model interface

```python
class AlphaModel(Protocol):
    name: str

    def predict_batch(
        self,
        universe: list[str],
        as_of: datetime,
        data_client: DataClient,
        portfolio_context: PortfolioContext | None,
    ) -> list[AlphaForecast]: ...
```

### 14.3 Portfolio constructor

MVP score:

```text
expected excess return
× calibrated confidence
× probability-positive adjustment
÷ recent volatility
```

Then:

- filter abstentions;
- minimum confidence;
- cross-sectional standardisation;
- long-only or market-neutral policy;
- turnover penalty;
- cash buffer;
- deterministic risk clamps.

### 14.4 Expanded risk policy

```python
class RiskPolicy(BaseModel):
    max_position_pct: float
    max_gross_exposure: float
    max_net_exposure: float
    max_turnover_pct: float
    minimum_cash_pct: float
    minimum_confidence: float
    maximum_sector_pct: float
    maximum_single_strategy_pct: float
    stale_price_minutes: int
    allow_shorting: bool
    allow_leverage: bool
```

Default demo:

```yaml
max_position_pct: 0.15
max_gross_exposure: 0.90
max_net_exposure: 0.90
max_turnover_pct: 0.30
minimum_cash_pct: 0.10
minimum_confidence: 0.55
maximum_sector_pct: 0.35
maximum_single_strategy_pct: 0.60
allow_shorting: false
allow_leverage: false
commission_bps: 5
slippage_bps: 5
```

---

## 15. Model routing and embeddings

### 15.1 Logical model aliases

```text
classify-fast
extract-structured
research-standard
research-deep
quant-code
bull-independent
bear-independent
judge-high
critic-independent
memory-synthesis
embedding-financial
rerank-financial
```

### 15.2 Routing inputs

- data classification;
- task type;
- schema reliability;
- required context;
- tool support;
- latency budget;
- cost budget;
- task-specific eval score;
- provider health;
- model correlation with other committee members.

### 15.3 Fallback

High-impact judgment falls back to another validated judge or to human review, not to an arbitrary cheap model.

### 15.4 Embeddings

Use embeddings for:

- filings;
- transcripts;
- news;
- social posts;
- theses;
- skills;
- memories;
- historical cases.

Do not use embeddings as the primary representation of:

- price series;
- financial statement numbers;
- portfolio weights;
- orders;
- risk metrics.

### 15.5 Replay provider

All agent calls must support a replay model provider that returns versioned recorded artifacts for fixtures.

---

## 16. Behavioral and graph capabilities

### 16.1 Behavioral features

- attention shock;
- message-volume acceleration;
- sentiment distribution;
- disagreement;
- narrative novelty;
- narrative saturation;
- cross-platform propagation;
- source/influencer concentration;
- abnormal price and volume;
- options/short-interest fields when available;
- continuation/overshoot/reversal probabilities.

### 16.2 Typed relation store

Use SQLite/PostgreSQL-style edge tables, not a separate graph database in the MVP.

```python
class TypedRelation(BaseModel):
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    graph_domain: str
    valid_from: datetime | None
    valid_to: datetime | None
    known_from: datetime
    known_to: datetime | None
    confidence: float
    evidence_ids: list[str]
```

Graph domains:

```text
evidence
economic
supply-chain
ownership
behavioral
portfolio-risk
actors
memory
skills
```

### 16.3 Graph-derived features

- supplier concentration;
- customer concentration;
- common ownership;
- sector exposure paths;
- narrative community centrality;
- actor influence and calibration;
- memory/skill dependency;
- portfolio connected-component concentration.

---

## 17. Self-improvement system

### 17.1 Improvement targets

The system may propose changes to:

- memories;
- skills;
- prompts;
- model routes;
- source routing;
- feature definitions;
- strategy candidates.

It may never autonomously change:

- hard risk policy;
- broker permissions;
- promotion thresholds;
- holdout data;
- authoritative ledgers.

### 17.2 Observation layer

Log:

- graph trajectory;
- tool calls;
- source results;
- evidence audit failures;
- agent abstentions;
- model/schema failures;
- cost and latency;
- forecast;
- portfolio result;
- realised outcome;
- attribution;
- human corrections.

### 17.3 Outcome classification

Victories:

```text
thesis-correct
timing-correct
execution-correct
risk-control
beta-driven
lucky
data-leak false victory
```

Failures:

```text
wrong evidence
missing evidence
point-in-time leakage
entity-resolution
reasoning
calibration
regime
sizing
liquidity
execution
external shock
```

### 17.4 Candidate loop

```text
observe
→ diagnose
→ propose
→ static tests
→ replay suite
→ historical evaluation
→ holdback
→ walk-forward/CPCV
→ PBO/DSR/cost stress
→ shadow candidate
→ human approval
→ promote or reject
```

### 17.5 Locked and editable boundaries

Locked:

- data loaders;
- timestamp rules;
- simulator;
- risk;
- ledger;
- evaluation periods;
- experiment history;
- promotion code.

Candidate-editable:

```text
skills/candidates/
prompts/candidates/
routing/candidates/
strategies/candidates/
features/candidates/
```

### 17.6 Learning candidate

```python
class LearningCandidate(BaseModel):
    candidate_id: str
    candidate_type: str
    target_id: str | None
    proposed_patch: str

    trigger_case_ids: list[str]
    evidence_ids: list[str]
    diagnosis: str
    expected_improvement: str

    falsifiable_metric: str
    minimum_required_delta: float

    applicable_entities: list[str]
    applicable_strategies: list[str]
    applicable_regimes: list[str]

    risk_class: str
    evaluation_suite_id: str
    proposer_model: str
    status: str
```

### 17.7 Skill performance registry

Track per skill version:

- invocation count;
- task success;
- evidence coverage;
- abstention;
- schema failures;
- cost;
- latency;
- forecast calibration;
- human corrections;
- candidate/rejection history.

The router can propose changes based on this registry, but cannot promote them directly.

### 17.8 Shadow operation

Candidate skills/prompts/routes run alongside the champion on replay and selected live research cases.

They do not affect the paper portfolio until approved.

### 17.9 Automatic low-risk changes

May auto-approve only when deterministically verified:

- source endpoint date semantics;
- parser version notes;
- temporary connector outage with expiry;
- cache invalidation behavior;
- local case working memory.

Everything else is staged.

---

## 18. Research lab and honest validation

### 18.1 Required experiment declaration

Before candidate code:

```text
HYPOTHESIS:
CHANGE:
WHY:
PARAMETER JUSTIFICATION:
EXPECTED FAILURE MODE:
```

### 18.2 Preflight

- qtype checks;
- syntax/type tests;
- data-schema tests;
- time-index alignment tests;
- rulelint-style mechanical condition replay where applicable.

### 18.3 Validation stages

```text
Development iteration
→ one-shot holdback
→ purged walk-forward
→ CPCV paths
→ PBO
→ PSR/DSR
→ cost/turnover/capacity stress
→ locked final holdout by human
```

### 18.4 Baselines

- benchmark ETF;
- equal weight;
- momentum-only;
- fundamental-only;
- deterministic composite;
- agent system without memory;
- agent system without Bull/Bear;
- one-model committee;
- full heterogeneous committee.

### 18.5 Experiment ledger

No experiment is deleted. Record:

- hypothesis;
- code commit;
- data snapshot;
- parameters;
- model/skill/prompt versions;
- result;
- costs;
- decision;
- parent experiment;
- number of prior trials.

---

## 18A. Research-paper and strategy-ingestion engine

The MVP should be able to turn a paper, repository, or strategy description into a **candidate research specification**, not an immediate trading rule.

### 18A.1 Inputs

- uploaded PDF or Markdown;
- arXiv/DOI or publisher URL where lawful access is available;
- GitHub strategy repository;
- blog or institutional research note;
- Papers With Backtest / Awesome Quant entry.

### 18A.2 Workflow

```text
source acquisition
→ immutable document capture
→ section/table extraction
→ methodology identification
→ data and timing requirements
→ candidate StrategySpec
→ ambiguity and missing-detail list
→ replication plan
→ locked research-lab experiment
```

### 18A.3 Output contract

```python
class PaperStrategyCandidate(BaseModel):
    candidate_id: str
    title: str
    authors: list[str]
    publication_date: date | None
    source_evidence_ids: list[str]

    economic_mechanism: str
    asset_classes: list[str]
    universe_definition: str | None
    signal_definition: str | None
    portfolio_formation: str | None
    holding_period: str | None
    rebalance_frequency: str | None

    required_data: list[str]
    point_in_time_requirements: list[str]
    transaction_cost_assumption: str | None
    reported_metrics: dict[str, float]

    ambiguities: list[str]
    unavailable_details: list[str]
    replication_tasks: list[str]
    status: Literal["draft", "replicable", "insufficient-detail", "validated", "rejected"]
```

### 18A.4 Paper-to-strategy skill

Add `skills/quant/paper-to-strategy/SKILL.md` with rules:

- distinguish quoted method from inferred implementation;
- never fabricate missing parameters;
- preserve original sample and universe definitions;
- flag publication lags and revised data;
- create deterministic replication tasks;
- require modern out-of-sample and cost testing;
- never promote from the paper's reported Sharpe alone.

### 18A.5 Knowledge-base integration

Approved paper summaries and replication outcomes may be projected into GBrain as:

```text
paper
→ proposes
strategy-hypothesis
→ tested-by
experiment
→ resolved-as
validated/rejected/conditional
```

The source document and experiment ledger remain authoritative.

---

## 19. Scheduler and autonomous monitoring

Use APScheduler or a simple persistent SQLite job table for the MVP.

Jobs:

```text
daily source health
watchlist source polling
weekly portfolio research cycle
weekly factor health
outcome maturity checks
nightly/weekly memory dream cycle
learning candidate evaluation
stale-memory review
```

Each job has:

- idempotency key;
- claimed/started/completed status;
- retry limit;
- last error;
- next run;
- output artifact IDs.

Do not build a full daemon platform or Temporal deployment in the MVP.

---

## 20. Reliability, security, and observability

### 20.1 Budgets

Per case:

- maximum agents;
- maximum depth;
- maximum source jobs;
- maximum pages;
- maximum tool calls;
- maximum tokens;
- maximum LLM cost;
- maximum wall time;
- one evidence-retry round.

### 20.2 Loop protection

Detect:

- repeated identical queries;
- repeated tool calls;
- A-B-A-B loops;
- no-new-evidence loops;
- duplicate agent artifacts;
- repeated failed source routes.

### 20.3 Circuit breakers

- source/connector failure;
- model provider failure;
- stale market data;
- memory backend failure;
- corrupt snapshot;
- broker ledger mismatch.

Research may degrade with warnings; portfolio/execution must halt on market-data or ledger integrity failure.

### 20.4 Reproducibility manifest

Every case records:

```text
code commit
container/environment lock hash
data snapshot
source manifest versions
raw evidence hashes
memory snapshot
relation snapshot
skill versions
prompt versions
model deployments
embedding/reranker versions
cost assumptions
random seeds
```

### 20.5 Observability

Track:

- case events;
- node start/end;
- model calls;
- tool calls;
- evidence acceptance/rejection;
- retrieval hits;
- memory use;
- costs;
- latency;
- errors;
- risk clamps;
- paper fills;
- learning candidates.

Use structured JSON logs plus an events table. Optional Langfuse/Logfire integration may be added later.

### 20.6 Security boundaries

- no broker credentials in agent/source workers;
- source-specific credentials only;
- browser worker has restricted filesystem/network;
- untrusted content never enters system prompt;
- memory writes require provenance;
- candidate code runs in a subprocess with resource and network restrictions;
- secrets redacted from traces and raw exports.

---

## 21. Storage for the MVP

### SQLite

Authoritative local metadata for:

- cases;
- graph events;
- evidence metadata;
- claims;
- memories and candidates;
- skills and versions;
- experiments;
- portfolio ledger;
- schedules.

### DuckDB + Parquet

- market and fundamental datasets;
- feature matrices;
- backtest outputs;
- high-volume analytic queries.

### Local object store

- raw web responses;
- PDFs and HTML;
- screenshots;
- normalised documents;
- model artifacts;
- generated reports.

### GBrain/PGLite sidecar

- long-term research-memory projection;
- hybrid retrieval;
- graph links;
- synthesis and gap analysis.

The app must continue to work with the local fallback if GBrain is unavailable.

---

## 22. Dashboard

Tabs:

1. **Case Intake** — mode, date, universe, mandate, budget.
2. **Agent Graph** — node status, retries, cost, abstention.
3. **Source Monitor** — connector health, jobs, crawl changes.
4. **Evidence Dossier** — source, timestamps, raw/normalised view, claims.
5. **Memory Recall** — retrieved memories, relevance, validity, source cases.
6. **Forecast** — specialist views, disagreement, Bull/Bear, CIO output.
7. **Portfolio & Risk** — proposed/final weights, clamps, cash, turnover.
8. **Backtest** — equity curve, benchmark, metrics, costs, robustness.
9. **Research Lab** — experiments, trial count, holdback/CPCV/PBO/DSR.
10. **Learning** — candidate memory/skill/prompt/strategy diffs and approval.
11. **Audit** — reproducibility manifest and complete event trail.

---

## 23. Capability-complete demo

### Demo 1 — deterministic replay

- five equities;
- one historical date;
- fixture structured data;
- three specialist agents;
- evidence audit;
- Bull/Bear/CIO;
- paper portfolio;
- backtest;
- postmortem;
- staged skill candidate.

### Demo 2 — live research with web acquisition

- current company;
- official filings first;
- Agent Reach channel for community/developer/video evidence;
- Scrapling fallback for one approved page;
- raw evidence and timestamps shown;
- GBrain prior-case recall;
- simulated recommendation only.

### Demo 3 — memory and improvement

- open a previous failed case;
- show attribution;
- show a candidate lesson;
- run replay evaluation against old cases;
- inspect the skill diff;
- approve/reject manually.

---

## 24. Build sequence and exit gates

### Release 0 — deterministic spine

Build:

- forked fund engine;
- extended contracts;
- batch alpha interface;
- fixtures;
- simulated broker and ledger;
- deterministic risk;
- no-key cycle and backtest.

**Exit gate:** same inputs reproduce the same portfolio and cycle receipt.

### Release 1 — agent harness and skills

Build:

- LangGraph state;
- context compiler;
- capability broker;
- skill loader;
- Coordinator, Quant, Fundamental, Event/Behavioral, Auditor, Bull/Bear, CIO, Verifier;
- replay model provider.

**Exit gate:** a full replay dossier is produced with evidence-linked artifacts.

### Release 2 — source intelligence

Build:

- source registry and planner;
- official/direct/RSS connectors;
- Agent Reach adapters;
- Scrapling static/dynamic workers;
- raw store;
- normalisation;
- source health and watchers;
- injection scan.

**Exit gate:** a live case acquires, stores, normalises, and cites web evidence while a historical case blocks it.

### Release 3 — memory and graph intelligence

Build:

- local memory backend;
- GBrain adapter;
- finance schema pack;
- memory candidate/governance pipeline;
- typed relation store;
- hybrid retrieval;
- dream cycle;
- memory dashboard.

**Exit gate:** relevant prior cases are retrieved without future leakage, and contradictory/stale memory is surfaced.

### Release 4 — research lab and improvement

Build:

- qtype;
- factor research skills;
- purgedcv/CPCV/PBO/DSR;
- experiment ledger;
- postmortem;
- learning candidates;
- replay/shadow evaluator;
- staged diff approval.

**Exit gate:** a candidate is either promoted or rejected through an auditable evaluation path; it cannot self-promote.

### Release 5 — presentation and robustness

Build:

- Streamlit dashboard;
- source monitor;
- complete audit view;
- golden-case tests;
- architecture diagrams;
- generated research report;
- polished README and demo script.

**Exit gate:** a recruiter can clone, run replay mode, inspect the complete decision trail, and reproduce the result.

---

## 25. Acceptance criteria

1. Fresh clone runs replay mode without keys.
2. Historical mode blocks live sources and future memory.
3. Every web result is stored raw before agent interpretation.
4. Agent Reach and Scrapling are accessed only through typed wrappers.
5. Scrapling jobs obey allowlists, limits, and mode policies.
6. Every material claim has evidence provenance.
7. Numeric claims reference coordinates or calculations.
8. Injection content is flagged and never obeyed.
9. Source and parser versions are recorded.
10. GBrain failure does not break replay mode.
11. Memory candidates require evidence, scope, confidence, and expiry.
12. Contradictory and superseded memories are visible.
13. Historical memory retrieval is point-in-time safe.
14. Bull and Bear opening memos are independent.
15. CIO cannot introduce evidence not present in approved artifacts.
16. Forecast Verifier can force abstention.
17. LLM failures abstain; held-position price failure halts.
18. Portfolio construction is deterministic.
19. Risk limits are deterministic and auditable.
20. Simulated orders reconcile to cash, positions, and NAV.
21. The same financial cycle is used for historical and paper modes.
22. Every experiment, including failures, remains in the ledger.
23. Candidate code cannot alter locked evaluation components.
24. qtype and time-alignment tests run before candidate backtests.
25. Baselines, ablations, PBO/DSR, costs, and drawdown appear in reports.
26. Candidate skill/prompt/strategy changes are staged as diffs.
27. Proposer and evaluator are separately recorded.
28. No candidate can affect the paper portfolio before promotion.
29. Every case has a reproducibility manifest.
30. Golden replay and scraping fixtures pass in CI.

---

## 26. Deferred capabilities

Defer until the MVP proves useful:

- live broker integration;
- Temporal;
- Kubernetes;
- Kafka/Redpanda;
- ClickHouse;
- Qdrant;
- Neo4j/Memgraph;
- GNNs;
- high-frequency data;
- options and derivatives portfolios;
- unrestricted browser automation;
- recursive subagents beyond one level;
- autonomous strategy promotion.

---

## 27. CV-ready project description after implementation

> **Built AegisQuant, an evidence-first hierarchical agentic investment research and paper-trading platform using LangGraph, point-in-time financial data, Markdown-based specialist skills, controlled web acquisition through Agent Reach/Scrapling, GBrain-backed hybrid memory, calibrated forecasts, deterministic portfolio/risk controls, and replayable end-to-end backtesting.**

> **Designed a governed continual-learning system that attributes forecast outcomes, stages memory/skill/model/strategy improvements, evaluates candidates through static leakage checks, purged/CPCV validation, PBO/DSR and shadow replays, and prevents autonomous changes to capital-critical controls.**

> **Implemented complete provenance and reproducibility across sources, evidence, agent artifacts, models, skills, memory snapshots, portfolio decisions, simulated fills and post-trade attribution.**

---

## 28. Final build rule

Do not begin with GBrain, Agent Reach, Scrapling, or self-improvement.

Build in this order:

```text
deterministic financial spine
→ replayable agent graph
→ evidence ledger
→ web acquisition
→ memory and graph recall
→ honest validation
→ governed self-improvement
```

Each intelligence layer is added only after the layer beneath it has deterministic tests and an auditable contract.
