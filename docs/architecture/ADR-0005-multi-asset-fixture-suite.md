# ADR-0005: Multi-asset fixture suite and governed paper execution

## Decision

The first research control is a deterministic, multi-asset, long-only fixture
harness. It uses frozen point-in-time data, explicit residual cash, next-bar
paper fills, policy-as-data checks, and governed-learning records. It remains
limited to `SIM` and `PAPER`.

The existing SPY/cash recommendation is superseded. No claim of alpha, live
readiness, broker connectivity, or automatic learning promotion is made.

## Consequences

Every research and trial artifact binds tenant, case, snapshot identifier,
manifest digest, content digest, and availability time. V1 Temporal history
remains fixed; reproducible research uses a new V2 workflow. Last30Days and
Scrapling are out of scope for this M0 fixture implementation.
