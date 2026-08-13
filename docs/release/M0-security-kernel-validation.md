# M0 security-kernel slice — validation record

- **Validated code commit:** `a6a70b3d805d4405037dd342763bceab9cd258cc`
- **Date:** 2026-08-08
- **Scope:** strict contracts, tenant boundary, case ledger, capability core, risk authorization cryptography, local immutable-object reference backend, fixture-only Temporal skeleton, and no-execution API boundary.
- **Release meaning:** pass for this implemented slice only; it is not full M0 completion, production approval, or live-trading readiness.

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

Validated toolchain and outcomes:

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
- Temporal historical replay, worker versioning, crash-after-side-effect and uncertain-outcome fixtures;
- production identity/mTLS/secrets/network policies;
- SBOM/AIBOM, provenance, signing, vulnerability/license/secret/container gates;
- production PostgreSQL role provisioning and migration ownership runbook;
- complete clean-room release evidence and recovery drills.
