"""Deterministic evidence audit that no model can override."""

from __future__ import annotations

from aegis.contracts import (
    AuditFinding,
    ClaimGraphSnapshot,
    EvidenceAuditPolicy,
    EvidenceAuditResult,
    EvidenceBundle,
    canonical_sha256,
)


def audit_evidence(
    bundle: EvidenceBundle,
    graph: ClaimGraphSnapshot,
    policy: EvidenceAuditPolicy,
) -> EvidenceAuditResult:
    findings: list[AuditFinding] = []
    evidence_by_id = {record.evidence_id: record for record in bundle.records}
    claim_by_id = {claim.claim_id: claim for claim in graph.claims}
    for claim in graph.claims:
        unknown = sorted(set(claim.evidence_ids).difference(evidence_by_id))
        if unknown:
            findings.append(
                AuditFinding(
                    code="unknown-claim-evidence",
                    severity="blocker",
                    message="claim cites evidence outside the audited bundle",
                    evidence_ids=unknown,
                    claim_ids=[claim.claim_id],
                )
            )
    for record in bundle.records:
        if record.extraction_confidence < policy.minimum_extraction_confidence:
            findings.append(
                AuditFinding(
                    code="low-extraction-confidence",
                    severity="blocker",
                    message="evidence extraction confidence is below policy",
                    evidence_ids=[record.evidence_id],
                )
            )
        if policy.block_injection_flags and record.injection_flags:
            findings.append(
                AuditFinding(
                    code="injection-flags",
                    severity="blocker",
                    message="untrusted source contains instruction-like content",
                    evidence_ids=[record.evidence_id],
                )
            )
        if policy.maximum_age_days is not None:
            age_days = (bundle.as_of - record.available_at).total_seconds() / 86400
            if age_days > policy.maximum_age_days:
                findings.append(
                    AuditFinding(
                        code="stale-evidence",
                        severity="blocker",
                        message="evidence is stale beyond policy",
                        evidence_ids=[record.evidence_id],
                    )
                )
    supported: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.source_kind == "evidence" and edge.relation == "SUPPORTS":
            supported.setdefault(edge.target_id, set()).add(edge.source_id)
    for claim in graph.claims:
        if claim.material and supported.get(claim.claim_id, set()) != set(claim.evidence_ids):
            findings.append(
                AuditFinding(
                    code="material-claim-support-mismatch",
                    severity="blocker",
                    message="material claim evidence and SUPPORTS edges do not match",
                    claim_ids=[claim.claim_id],
                )
            )
    claim_by_id = {claim.claim_id: claim for claim in graph.claims}
    for numeric in graph.numeric_claims:
        numeric_parent = claim_by_id.get(numeric.claim_id)
        if (
            numeric.evidence_id not in evidence_by_id
            or numeric_parent is None
            or numeric.evidence_id not in numeric_parent.evidence_ids
            or not numeric.coordinates
            or not numeric.calculation_id
        ):
            findings.append(
                AuditFinding(
                    code="numeric-provenance",
                    severity="blocker",
                    message=(
                        "exact numeric claim lacks linked evidence, coordinates, or calculation"
                    ),
                    evidence_ids=[numeric.evidence_id],
                    claim_ids=[numeric.claim_id],
                )
            )
    blockers = [finding for finding in findings if finding.severity == "blocker"]
    input_hash = canonical_sha256({"bundle": bundle, "graph": graph, "policy": policy})
    return EvidenceAuditResult(
        case_id=bundle.case_id,
        approved=not blockers,
        approved_evidence_ids=[] if blockers else sorted(evidence_by_id),
        approved_claim_ids=[] if blockers else sorted(claim_by_id),
        findings=findings,
        audited_input_hash=input_hash,
    )
