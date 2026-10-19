# Release-gate Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local release, recovery, and venue-fixture checks fail closed for the four audited gaps.

**Architecture:** Reuse the local immutable store as the evidence and full-tenant-inventory source.
Release verification loads signed `BlobRef` evidence, recovery verifies the whole local tenant set and
freshness, and venue conformance drives the existing Ed25519 risk gate through recorded lifecycle
fixtures. The result remains a local PAPER safety proof, not a live deployment path.

**Tech Stack:** Python 3.12, Pydantic strict models, `cryptography` Ed25519, pytest, PostgreSQL
verification scripts.

## Global Constraints

- Keep `TradingEnvironment` limited to `SIM` and `PAPER`.
- Add no dependencies, network calls, credentials, broker SDKs, or execution endpoints.
- Use `digest_canonical`, UTC datetimes, strict models, tenant-bound `BlobRef`s, and fail-closed
  errors at every trust boundary.
- Run generated-schema checks after every contract change; do not commit without explicit approval.

---

### Task 1: Bind release evidence and recovery freshness

**Files:**
- Modify: `src/aegisquant/contracts/release.py`
- Modify: `src/aegisquant/case_cli.py`
- Modify: `tests/test_release_gate.py`
- Modify: `scripts/export_contract_schemas.py`

**Interfaces:**
- Produces `ReleaseEvidenceReference`, `ProductionReleaseManifest.evidence_references`, and
  `max_recovery_drill_age_seconds`.
- Consumes a tenant-scoped immutable store through `LocalImmutableObjectStore.get`.

- [ ] **Step 1: Write failing tests**

```python
def test_release_cli_rejects_stale_or_missing_bound_evidence() -> None:
    # A signed manifest with a receipt older than its maximum age, or an absent BlobRef, exits nonzero.
    assert main([...]) == 2
```

- [ ] **Step 2: Run the focused test and verify it fails because the manifest has no evidence
  references or freshness check**

Run: `uv run pytest -q tests/test_release_gate.py`

- [ ] **Step 3: Implement the minimum contract and verification changes**

```python
class ReleaseEvidenceReference(StrictModel):
    evidence_name: ReleaseEvidenceName
    payload: BlobRef


# Require one tenant-bound reference for every signed manifest digest, then read each payload.
if now - receipt.completed_at > timedelta(seconds=manifest.max_recovery_drill_age_seconds):
    raise ValueError("release recovery receipt is stale")
```

- [ ] **Step 4: Run focused release tests and schema export check**

Run: `uv run pytest -q tests/test_release_gate.py && uv run python scripts/export_contract_schemas.py --check`

### Task 2: Verify complete local recovery inventory

**Files:**
- Modify: `src/aegisquant/object_store/local_immutable.py`
- Modify: `src/aegisquant/object_store/recovery.py`
- Modify: `src/aegisquant/contracts/recovery.py`
- Modify: `tests/test_object_store_recovery.py`

**Interfaces:**
- Produces `LocalImmutableObjectStore.references_for_tenant(tenant_id) -> tuple[BlobRef, ...]`.
- Consumes sorted `ObjectStoreRecoveryCommand.source_references` as the full local inventory.

- [ ] **Step 1: Write failing tests**

```python
def test_recovery_rejects_partial_inventory_and_nested_target(tmp_path: Path) -> None:
    # One omitted source object and a target inside the source root must both raise.
```

- [ ] **Step 2: Run the focused test and verify it fails because the current drill accepts both**

Run: `uv run pytest -q tests/test_object_store_recovery.py`

- [ ] **Step 3: Implement the minimum inventory scan and restore guard**

```python
actual = source.references_for_tenant(command.tenant_id)
if actual != command.source_references:
    raise ObjectStoreRecoveryError("recovery command does not cover the complete tenant inventory")
if target.root.is_relative_to(source.root) or source.root.is_relative_to(target.root):
    raise ObjectStoreRecoveryError("recovery roots must not be nested")
```

- [ ] **Step 4: Run focused recovery tests**

Run: `uv run pytest -q tests/test_object_store_recovery.py`

### Task 3: Bind venue fixtures to signed risk authorization and lifecycle evidence

**Files:**
- Modify: `src/aegisquant/contracts/risk.py`
- Modify: `src/aegisquant/contracts/venue.py`
- Modify: `src/aegisquant/venue/conformance.py`
- Modify: `tests/test_venue_conformance.py`
- Modify: `scripts/export_contract_schemas.py`

**Interfaces:**
- Produces an operator-owned serialized risk-trust-store and venue risk-authorization fixture models.
- Consumes `SignedRiskDecision`, exact `OrderBundle`, risk context, and one lifecycle fixture per
  client order.

- [ ] **Step 1: Write failing tests**

```python
def test_venue_conformance_rejects_missing_risk_binding_and_unexercised_lifecycle() -> None:
    # Unsigned/mismatched decisions, a replayed nonce, timeout overrun, ID drift, missing status,
    # and missing cancellation must fail.
```

- [ ] **Step 2: Run the focused test and verify it fails because current conformance sees only an
  OrderBundle and acknowledgements**

Run: `uv run pytest -q tests/test_venue_conformance.py`

- [ ] **Step 3: Implement the minimum recorded fixture checks**

```python
payload = ExecutionAuthorizationGate(verifier, InMemoryDecisionConsumptionStore()).authorize_once(
    authorization.decision, bundle, authorization.context(), now=now
)
if command.risk_decision_digest != digest_canonical(authorization.decision):
    raise VenueConformanceError("venue command risk authorization is mismatched")
# Each lifecycle must show one bounded timeout, retry acceptance, status lookup, and cancellation
# for the same client and venue order IDs.
```

- [ ] **Step 4: Run focused venue tests and schema export check**

Run: `uv run pytest -q tests/test_venue_conformance.py && uv run python scripts/export_contract_schemas.py --check`

### Task 4: Update operational truth and run the full gate

**Files:**
- Modify: `README.md`
- Modify: `docs/BUILD_PLAN.md`
- Modify: `docs/architecture/ADR-0006-production-release-gate.md`
- Modify: `docs/architecture/ADR-0007-jurisdiction-neutral-venue-conformance.md`
- Modify: `docs/operations/production-release.md`
- Test: `tests/test_release_gate.py`, `tests/test_object_store_recovery.py`,
  `tests/test_venue_conformance.py`

- [ ] **Step 1: State the local-proof boundary precisely**

```markdown
The local restore exercise proves complete tenant restoration within this backend. It does not prove
an independent backup/failure domain; external attestation remains required before LIVE is considered.
```

- [ ] **Step 2: Run all contract and behavior checks**

Run: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run python scripts/export_contract_schemas.py --check && uv run pytest -q`

- [ ] **Step 3: Run database-integrity verification and inspect the diff**

Run: `git diff --check && uv lock --check && scripts/verify.sh`

## Self-review

- Spec coverage: Task 1 covers evidence presence/freshness; Task 2 covers selected-subset and nested
  restore failures; Task 3 covers signed authorization and every asserted venue capability; Task 4
  prevents documentation from calling a local exercise disaster recovery.
- Placeholder scan: no TODO/TBD or deferred implementation steps are present.
- Type consistency: `ReleaseEvidenceReference` carries `BlobRef`; recovery returns existing
  `ObjectStoreRecoveryReceipt`; venue uses existing `SignedRiskDecision`, `RiskDecisionVerifier`,
  and `ExecutionAuthorizationGate`.
