# Personal production release procedure

This procedure validates M6 prerequisites. It does not enable LIVE execution or place an order.

## 1. Produce real evidence

Create immutable reports for the exact release, store each canonical report in the configured
immutable object store, and bind its `BlobRef` to the matching manifest digest. Do not use
placeholder digests or references. Select an immutable compliance-policy pack for the deployment; it carries the applicable
jurisdiction, data-rights, and broker evidence without hard-coding them into AegisQuant. The signed
manifest requires:

- built artifact and CI SBOM;
- applied PostgreSQL migration set and non-owner tenant role audit;
- chosen object-store conformance plus a successful backup-and-restore drill;
- Temporal/API process interruption and recovery drill;
- independent security assessment and model validation;
- jurisdiction-specific legal/compliance determination;
- current data-rights and broker agreements;
- exact risk, network-egress, and secrets-management policies.

The broker fields must name the real account boundary and exact API DNS hostnames. Keep secrets and
private keys out of JSON and out of the repository.

## 2. Sign and trust independently

An independent reviewer signs the exact manifest digest first. A different human operator signs it
after review. Signing must occur in the OS key store or an HSM/KMS boundary; the in-process signer
in `release_attestation.py` is development/test support only.

Create a public-key trust store matching `release-trust-store-v1.json`. It must be owned by the
operator, must not be a symlink, and must not be group- or other-writable:

```bash
chmod 600 /absolute/path/release-trust.json
```

## 3. Verify the running dependencies

Configure the existing tenant-bound application role and the active Temporal deployment, plus an
absolute local immutable-object path:

```bash
export AEGISQUANT_POSTGRES_DSN='postgresql://...'
export AEGISQUANT_TEMPORAL_TARGET='127.0.0.1:7233'
export AEGISQUANT_TEMPORAL_NAMESPACE='aegisquant'
export AEGISQUANT_TEMPORAL_BUILD_ID='exact-build-id'
export AEGISQUANT_OBJECT_STORE_ROOT='/absolute/private/aegisquant-objects'
uv run aegisquant-case release verify /absolute/path/release.json \
  --trust-store /absolute/path/release-trust.json \
  --recovery-receipt /absolute/path/recovery-receipt.json
```

Success means the signed local prerequisites, stored evidence, fresh local restore evidence, and
current local dependencies verified. It deliberately returns `live_execution_enabled: false` and
`VENUE_ADAPTER_AND_EXTERNAL_ACCEPTANCE` until the venue-specific milestone is implemented and
accepted.

## 4. Exercise recovery and venue conformance

Use a fresh, empty, non-nested target path to restore the complete local tenant inventory; the
drill will never overwrite it:

```bash
uv run aegisquant-case recovery drill /absolute/path/recovery-command.json \
  --source-root /absolute/private/aegisquant-objects \
  --target-root /absolute/private/aegisquant-restore-drill
uv run aegisquant-case venue verify /absolute/path/venue-conformance.json \
  --risk-trust-store /absolute/path/risk-trust.json
```

`venue verify` is recorded-fixture validation only. It requires an operator-owned, non-symlink risk
public-key policy, a signed hard-risk authorization, and one bounded timeout/retry/status/cancel
lifecycle per order. It establishes exact interface
invariants for a future provider adapter; it does not connect to a broker or submit an order. The
local restore exercise does not prove an independent backup or failure domain; obtain an external
recovery attestation before any future LIVE acceptance.

## 5. Stop conditions

Do not proceed when a signature, digest, hostname, trust-store permission, dependency probe,
recovery drill, contract, approval, or expiry is missing. Revoke the affected release key and
issue a new manifest after any artifact, broker account, hostname, policy, or deployment changes.
