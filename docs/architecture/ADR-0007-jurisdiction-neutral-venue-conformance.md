# ADR-0007: Jurisdiction-neutral venue conformance foundation

- **Status:** Accepted for fixture-only integration preparation
- **Date:** 2026-08-14

## Context

The core must not encode one country's law, broker API, market convention, credential mechanism,
or order lifecycle. At the same time, a generic network adapter would conceal venue-specific order,
cancel, status, idempotency, and reconciliation semantics.

## Decision

1. The release gate refers only to an immutable `compliance_policy_pack_id` and digest. The pack is
   selected per deployment and carries the external legal, rights, and broker evidence; the core
   does not interpret or hard-code jurisdictional rules.
2. Add a no-transport venue conformance contract: a reviewed adapter profile, exact release/policy
   binding, exact hostname, an operator-owned risk public-key policy, exact signed hard-risk
   decision/nonce/context, exact authorized PAPER
   order bundle, client request ID, and one timeout/retry/status/cancel lifecycle fixture per order.
   The existing hard-risk gate verifies the signature and one-time nonce in the fixture path.
3. `aegisquant-case venue verify` accepts only recorded fixtures. It cannot connect, authenticate,
   send, cancel, or observe an order.
4. Add `aegisquant-case recovery drill` to restore the complete local tenant inventory into a
   fresh, non-nested local target and issue a content-bound receipt. It has a declared byte limit
   and never deletes a source or existing target. It does not claim independent backup durability
   or a distinct failure domain.
5. A concrete provider adapter remains a separate Temporal Activity and must pass this conformance
   suite plus a provider-specific ADR, threat model, sandbox certification, reconciliation/retry
   drill, credential-boundary review, and independent review before it may introduce `LIVE`.

## Consequences

The architecture is jurisdiction-neutral while each deployment remains evidence-bound to a selected
policy pack. The new commands reduce integration and recovery ambiguity, but they do not establish
legal compliance, broker approval, production storage durability, or live-trading authorization.
