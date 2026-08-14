# M0 security-kernel slice — validation record

- **Validated code commit:** `a6a70b3d805d4405037dd342763bceab9cd258cc`.
- **Validation date:** 2026-08-08.
- **Scope:** the original M0 strict contracts, tenant boundary, case ledger, capability core, risk
  authorization cryptography, local immutable-object reference backend, fixture-only Temporal
  skeleton, and no-execution API boundary.
- **Release meaning:** historical validation for that exact commit only; it does not validate the
  current M1-M5 fixture candidate, production use, or live-trading readiness.

## Independent review

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

## Still open before full M0 exit

- production object-store conformance/WORM/restore selection;
- durable Temporal/PostgreSQL paper execution and recovery validation;
- production identity/mTLS/secrets/network policies;
- deployment provenance/signing and recovery drills beyond the local CI gate;
- production PostgreSQL role provisioning and migration ownership runbook;
- complete clean-room release evidence and recovery drills.
