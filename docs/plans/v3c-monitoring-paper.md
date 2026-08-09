# v3C — Monitoring & Persistent Paper Fund Plan

## Deliverables
1. Source monitor -> `EventCandidate` -> idempotent research-case trigger.
2. Exchange-session adapter with deterministic fixture fallback.
3. Append-only persistent paper book for positions, cash, NAV, orders/fills, cycle keys and reconciliation receipts.
4. Paper service/scheduler restoring state before cycle, calling the existing target/risk/order/run-cycle authority and refusing duplicate cycle keys.
5. Twenty-cycle fixture run, restart/recovery and event-trigger fixtures.
6. CLI `paper start/status` and read-only dashboard fund/source views.

## Gate tests
20 cycles; cash/NAV conservation; duplicate prevention; restart equivalence; session eligibility; source-event deduplication; costs; reconciliation; model/agent cannot order; no live broker.
