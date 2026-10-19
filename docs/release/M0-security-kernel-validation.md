# Offline security kernel and durable-case validation record

## Current durable-offline candidate

- **Validated code commit:** `2f05a8c593ecf1d0d1ba254d12a2690d4beebdf7`.
- **Validation date:** 2026-08-14.
- **Scope:** deterministic fixture research, PostgreSQL-backed PAPER state/result persistence,
  replay-safe Temporal orchestration, evidence-bound forecasts with `ABSTAIN`, multi-period PIT
  evaluation, complete offline risk denials, dependency-aware health/CLI controls, and signed
  manual learning promotion. No callable public-web transport or runtime source gateway is present.
- **Release meaning:** validated local offline candidate only. It is not production certification,
  investment performance evidence, custody validation, or live-trading authorization.

### Observed gate

From `/Users/raghav/Desktop/AegisQuant`, `scripts/verify.sh` completed with exit 0:

```text
uv 0.11.15
Python 3.12.13
Ruff 0.16.2                         format and lint passed
mypy 2.3.0                         50 source files passed
pytest 9.1.1                       168 passed
PostgreSQL client 16.13            ephemeral migration gate passed
JSON Schema export                current
```

The PostgreSQL gate verified bound-tenant RLS, DB-owned event chains, atomic idempotency, and
append-only rejection. Temporal tests injected failures around durable commits and reconciled one
result without duplicate application; committed history replayed offline. Multi-period reports
were independently recomputed. Learning application required current trusted evaluator and human
signatures, an unexpired approval, and exact source, holdout, case, baseline, evaluation, proposal,
and rollback bindings.

### Independent review

Read-only review returned `READY` after blocking issues were corrected. Closure covered caller-
asserted outcome sufficiency, forgeable evaluator/human records, missing case/holdout bindings,
V1 compatibility, expired/revoked-key backdating, signed approval validity windows, callable
network ingress, holdout entry state, compounded OOS/control gates, and terminal delisting.

## Historical M0 kernel validation

- **Validated code commit:** `a6a70b3d805d4405037dd342763bceab9cd258cc`.
- **Validation date:** 2026-08-08.
- **Scope:** the original M0 strict contracts, tenant boundary, case ledger, capability core, risk
  authorization cryptography, local immutable-object reference backend, fixture-only Temporal
  skeleton, and no-execution API boundary.
- **Release meaning:** historical validation for that exact commit only; it does not validate the
  current M1-M5 fixture candidate, production use, or live-trading readiness.

### Independent review

A read-only agent that did not author the implementation performed three adversarial rounds. Initial findings were one P0 and five P1 items. It independently re-tested every correction. Final verdict:

> PASS. No audited P0/P1 blockers remain for the implemented slice.

Closure probes included:

- bound database tenant identity and cross-role denial;
- nested cross-tenant reference rejection;
- omitted capability scope/domain, privilege, revocation, call/cost, and negative-cost bypasses;
- strict runtime/schema types;
- typed-canonical collision and idempotency conflicts;
- immutable object byte and metadata tamper/downgrade attempts;
- exact-order Ed25519 context, expiry, revocation, mutation, and replay checks;
- DB-owned, full-row-bound event preimage/content/chain digests shared with Python;
- arbitrary sequence/predecessor, fake preimage/digest, mutation, and changed-idempotency attempts;
- absence of `LIVE`, broker SDKs, broker destinations, credentials, adapters, and order-submission routes.

## Reproduction

CWD: `/Users/raghav/Desktop/AegisQuant`

```bash
uv lock --check
scripts/verify.sh
```

Historical validated toolchain and outcomes for the exact commit above:

```text
uv 0.11.15                              exit 0
Python 3.12.13                          exit 0
Ruff 0.16.2                             exit 0
mypy 2.3.0                              exit 0
pytest 9.1.1                            exit 0 — 36 passed
PostgreSQL client 16.13                 exit 0
ephemeral PostgreSQL security test      exit 0
```

The PostgreSQL script creates uniquely named temporary roles/database, runs bound-RLS, field-bound chain, idempotency, and append-only adversarial checks, and removes all temporary resources through a cleanup trap.

## Still open before production or any live-readiness claim

- production object-store conformance/WORM/restore selection;
- production identity/mTLS/secrets/network policies;
- deployment provenance/signing and recovery drills beyond the local CI gate;
- production PostgreSQL role provisioning and migration ownership runbook;
- live service/process recovery drills using production-equivalent infrastructure;
- legal, compliance, broker/data contracts, model validation, and explicit approval for any future
  capability beyond offline `SIM`/`PAPER`.
