# ADR-0006: Signed M6 release gate before venue integration

- **Status:** Accepted for the production-readiness foundation
- **Date:** 2026-08-14

## Context

The durable offline candidate proves deterministic research, risk authorization, paper execution,
recovery, and reconciliation. Those properties do not prove that a real deployment, broker
account, data right, legal determination, backup, or recovery procedure is acceptable. A generic
broker abstraction would hide venue-specific failure semantics and would not make LIVE execution
safe.

## Decision

1. Keep `TradingEnvironment` limited to `SIM` and `PAPER` until one jurisdiction and broker are
   selected and reviewed. The M6 gate does not add an execution path.
2. Bind one release to exact deployment, SBOM, database, object-store, backup/restore,
   service-recovery, security, model-validation, legal/compliance, data-rights, broker-agreement,
   risk-policy, network-policy, and secrets-management evidence digests.
3. Bind the same manifest to the exact tenant, legal entity, account, broker, immutable compliance
   policy-pack ID/digest, and sorted exact DNS hostname allowlist. Wildcards, URLs, ports, and IP
   literals are rejected. The policy pack carries deployment-specific jurisdiction evidence; the
   core does not hard-code a jurisdiction.
4. Require a current Ed25519 attestation from an independent reviewer followed by a different
   human operator. Trusted keys are tenant-, actor-, role-, time-, and revocation-scoped.
5. Load public-key policy only from an operator-owned, non-symlink file that group and other users
   cannot modify.
6. `aegisquant-case release verify` must also prove the configured PostgreSQL and Temporal
   deployment are ready, bind an immutable-object recovery receipt, and round-trip a tenant-bound
   immutable object-store probe.
7. A later venue adapter must be a Temporal Activity with atomic submission idempotency,
   broker-order reconciliation, bounded timeouts, an exact egress allowlist, a kill switch, and no
   public mutation API. It needs its own ADR, threat model, recorded contract tests, sandbox/paper
   certification, and explicit operator acceptance before `LIVE` can exist.

## Consequences

The repository now has a verifiable production-release prerequisite gate without pretending that
self-authored files prove external legal, broker, security, or operational acceptance. The CLI
reports `live_execution_enabled: false` until a reviewed venue adapter exists. No credential or
private signing key is stored by this gate.
