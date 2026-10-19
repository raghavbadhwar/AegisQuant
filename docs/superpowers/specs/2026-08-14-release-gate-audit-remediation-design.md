# Release-gate audit remediation

## Goal

Close the four P1 findings from the read-only audit without expanding the M0 fixture-only
execution boundary.

## Chosen approach

Extend the existing typed contracts, canonical digests, Ed25519 risk verifier, and local immutable
store. This keeps every new claim replayable and fail-closed, while avoiding a broker abstraction,
network transport, or a second evidence system.

The implementation has four bounded changes:

1. A release manifest will bind every named evidence digest to an immutable `BlobRef`. Release
   verification will retrieve every referenced object from the configured store before returning a
   local-prerequisite result. This verifies presence and byte integrity, not the legal or technical
   merit of an evidence document.
2. A recovery drill will require the command's reference set to equal the complete local tenant
   inventory, reject nested source/target roots, and enforce a signed maximum drill age. It remains
   a local restore exercise: an external backup/failure-domain attestation remains mandatory before
   any future LIVE milestone.
3. A venue fixture will carry a signed hard-risk decision and an exact risk context. Conformance will
   load an operator-owned, non-symlink risk public-key store, then use the existing risk verifier and
   single-use gate,
   bind the decision/nonce/snapshots into the command, and reject state, epoch, or signature drift.
4. Each submitted order will require a recorded timeout, retry acceptance, status observation, and
   cancellation observation with one stable venue order ID. This turns the profile's current
   self-asserted capabilities into exercised fixture behavior. The verifier remains PAPER-only.

## Alternatives rejected

- A generic broker adapter: it adds a transport surface before a venue has been selected.
- Accepting a caller-supplied recovery subset or a boolean capability profile: both allow a green
  report without proving the claimed behavior.
- Treating a local directory copy as disaster recovery: a single-host fixture cannot establish an
  independent backup or failure domain.

## Error handling and tests

All validation is deny-by-default. Tests must be written first and demonstrate stale receipts,
partial inventory, nested targets, absent/tampered evidence objects, missing or invalid risk
authorization, reused risk nonce, timeout overflow, retry ID drift, status mismatch, and
cancellation mismatch. Existing SIM/PAPER-only contracts and no-network behavior remain unchanged.

## Non-goals

No LIVE enum, credentials, broker SDK, network request, legal-policy interpretation, actual
provider certification, automatic learning/policy promotion, or claim that local tests are external
production acceptance.
