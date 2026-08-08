# ADR-0001: Security-kernel-first build order

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

The consolidated design is directionally strong, but independent review found that tenant identity, capability grants, immutable evidence, workflow replay, approval subject binding, data rights, egress, credentials, and supply-chain controls were described rather than enforced.

## Decision

Build an M0 security kernel before internet retrieval, model calls, private/licensed data, quant claims, or any execution adapter. M0 contains no `LIVE` enum value and no externally reachable execution endpoint.

Temporal remains the only durable workflow owner. PydanticAI is a typed agent runtime; when introduced, its current `TemporalDurability` capability will route model and tool I/O through Temporal activities. No parallel LangGraph/Pydantic Graph checkpoint owner is added.

Tenant identity is derived from authenticated workload/user context, not accepted from an LLM. Every authoritative record is tenant scoped. Authorization is completely mediated and deny-by-default.

Risk approval signs the exact normalized order bundle and current state manifest, not prose or target weights alone. A decision is single-use, scoped to `SIM` or `PAPER`, epoch-bound, and verified locally by the execution boundary.

## Consequences

The first milestone is narrower than the original Phase 1, but removes costly security retrofits. Internet adapters, GBrain, LiteLLM, quant models, and NautilusTrader remain replaceable adapters until their acceptance gates pass.
