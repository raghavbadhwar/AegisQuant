# Architecture

```mermaid
flowchart LR
  S[Mode-gated source gateway] --> R[Immutable raw store]
  R --> N[Safe normalization and injection scan]
  N --> E[Evidence + claim graph + deterministic audit]
  M[Governed PIT memory] --> G[LangGraph specialist desk]
  E --> G
  G --> F[Typed AlphaForecasts]
  F --> P[Deterministic portfolio construction]
  P --> K[Hard risk gate]
  K --> B[SimBroker only]
  B --> L[Tamper-evident cycle ledger]
  O[Outcomes] --> X[Candidate-only research lab]
  X --> H[Human promotion decision]
```

One modular Python application owns one financial path: `aegis.fund.run_cycle.run_cycle`. The graph ends at forecasts. Source workers, memory, research-lab candidates, and the dashboard have no broker capability. Replay and historical providers are sealed local implementations. Live research may acquire approved public evidence, but execution remains simulated paper.
