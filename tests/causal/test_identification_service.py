from datetime import UTC, datetime

import pytest

from aegis.causal import (
    CausalEdge,
    CausalEdgeKind,
    CausalGraphSnapshot,
    CausalIdentificationService,
    CausalSupportLevel,
    CausalToolAbstention,
    CausalToolUnavailable,
    DoWhyAdapter,
    EdgeStatus,
    IdentificationRecord,
    IdentificationRequest,
    IdentificationStatus,
    RefutationRecord,
    RefutationStatus,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)
DOMAIN = "ai-infrastructure-v1"


def graph(*, sealed: bool = True, confounders: tuple[str, ...] = ()) -> CausalGraphSnapshot:
    snapshot = CausalGraphSnapshot(
        snapshot_id="ai-capex-acceleration",
        as_of=NOW,
        domain_pack=DOMAIN,
        edges=(
            CausalEdge(
                edge_id="ai-capex-to-supplier-revenue",
                source_variable_id="ai-capex",
                target_variable_id="supplier-revenue",
                kind=CausalEdgeKind.HYPOTHESIZED_CAUSE,
                status=EdgeStatus.DRAFT,
                support_level=CausalSupportLevel.C0_NARRATIVE,
                mechanism_description="Candidate demand transmission mechanism.",
                sign=1,
                evidence_ids=("filing-1",),
                assumption_ids=("capacity-available",),
                confounder_ids=confounders,
                domain_pack=DOMAIN,
                known_from=NOW,
                confidence=0.2,
            ),
        ),
        evidence_ids=("filing-1",),
    )
    return snapshot.sealed() if sealed else snapshot


def request(**updates: object) -> IdentificationRequest:
    values: dict[str, object] = {
        "request_id": "identify-ai-capex-1",
        "causal_graph": graph(),
        "edge_id": "ai-capex-to-supplier-revenue",
        "method": "difference-in-differences",
        "adjustment_set": (),
        "assumption_ids": ("capacity-available",),
        "evidence_ids": ("filing-1",),
        "refutation_methods": ("placebo-treatment",),
    }
    values.update(updates)
    return IdentificationRequest(**values)


class PassingAdapter:
    def identify(self, candidate: IdentificationRequest) -> IdentificationRecord:
        return IdentificationRecord(
            identification_id="identified-ai-capex-1",
            method=candidate.method,
            adjustment_set=candidate.adjustment_set,
            assumption_ids=candidate.assumption_ids,
            evidence_ids=candidate.evidence_ids,
            refutations=(
                RefutationRecord(
                    refutation_id="placebo-pass",
                    method="placebo-treatment",
                    status=RefutationStatus.PASSED,
                    assumption_ids=candidate.assumption_ids,
                    evidence_ids=candidate.evidence_ids,
                    evaluated_at=NOW,
                    evaluator_id="deterministic-golden-adapter",
                    reason="Golden placebo test passed.",
                ),
            ),
            validated_at=NOW,
            validator_id="deterministic-golden-adapter",
        )


class MustNotRunAdapter:
    def identify(self, candidate: IdentificationRequest) -> IdentificationRecord:
        raise AssertionError(f"adapter must not run for {candidate.request_id}")


class FailedRefutationAdapter:
    def identify(self, candidate: IdentificationRequest) -> IdentificationRecord:
        raise CausalToolAbstention(
            IdentificationStatus.REFUTATION_FAILED,
            f"placebo refutation failed for {candidate.edge_id}",
        )


def test_golden_ai_capex_case_identifies_without_promoting_the_candidate_edge() -> None:
    candidate = request()

    outcome = CausalIdentificationService(PassingAdapter()).identify(candidate)

    assert outcome.status == IdentificationStatus.IDENTIFIED
    assert outcome.identification is not None
    assert outcome.authority == "candidate_only"
    assert outcome.causal_graph_hash == candidate.causal_graph.content_hash
    assert candidate.causal_graph.edges[0].kind == CausalEdgeKind.HYPOTHESIZED_CAUSE
    assert candidate.causal_graph.edges[0].status == EdgeStatus.DRAFT


def test_golden_unsupported_counterfactual_abstains_when_a_confounder_is_omitted() -> None:
    candidate = request(causal_graph=graph(confounders=("macro-demand",)))

    outcome = CausalIdentificationService(MustNotRunAdapter()).identify(candidate)

    assert outcome.status == IdentificationStatus.NOT_IDENTIFIED
    assert "confounder" in outcome.reason
    assert outcome.identification is None


def test_failed_refutation_returns_only_an_explicit_abstention() -> None:
    outcome = CausalIdentificationService(FailedRefutationAdapter()).identify(request())

    assert outcome.status == IdentificationStatus.REFUTATION_FAILED
    assert outcome.identification is None


def test_unsealed_graph_fails_closed_before_the_optional_tool_boundary() -> None:
    outcome = CausalIdentificationService(MustNotRunAdapter()).identify(
        request(causal_graph=graph(sealed=False))
    )

    assert outcome.status == IdentificationStatus.NOT_IDENTIFIED
    assert "sealed" in outcome.reason


def test_malformed_public_request_returns_a_typed_not_identified_abstention() -> None:
    malformed = IdentificationRequest.model_construct(
        request_id="malformed-request",
        causal_graph={},
        edge_id="edge-1",
        method="difference-in-differences",
        assumption_ids=("assumption-1",),
        evidence_ids=("evidence-1",),
        refutation_methods=("placebo",),
    )

    outcome = CausalIdentificationService(MustNotRunAdapter()).identify(malformed)

    assert outcome.status == IdentificationStatus.NOT_IDENTIFIED
    assert outcome.request_id == "malformed-request"
    assert outcome.edge_id == "edge-1"
    assert outcome.causal_graph_hash is None


def test_malformed_public_request_with_exploding_graph_metadata_still_abstains() -> None:
    class ExplodingGraph:
        @property
        def content_hash(self) -> str:
            raise RuntimeError("untrusted graph metadata access")

    malformed = IdentificationRequest.model_construct(
        request_id="malformed-request",
        causal_graph=ExplodingGraph(),
        edge_id="edge-1",
        method="difference-in-differences",
        assumption_ids=("assumption-1",),
        evidence_ids=("evidence-1",),
        refutation_methods=("placebo",),
    )

    outcome = CausalIdentificationService(MustNotRunAdapter()).identify(malformed)

    assert outcome.status == IdentificationStatus.NOT_IDENTIFIED
    assert outcome.causal_graph_hash is None


def test_golden_all_models_abstain_when_dowhy_is_unavailable(monkeypatch) -> None:
    def unavailable(_: str) -> object:
        raise ModuleNotFoundError("No module named 'dowhy'", name="dowhy")

    monkeypatch.setattr("aegis.causal.adapters.import_module", unavailable)
    adapter = DoWhyAdapter()
    candidate = request()

    with pytest.raises(CausalToolUnavailable) as raised:
        adapter.identify(candidate)
    assert raised.value.status == IdentificationStatus.TOOL_UNAVAILABLE

    outcome = CausalIdentificationService(adapter).identify(candidate)
    assert outcome.status == IdentificationStatus.TOOL_UNAVAILABLE
    assert outcome.identification is None
    assert outcome.authority == "candidate_only"


def test_direct_dowhy_adapter_revalidates_before_importing_the_optional_tool(monkeypatch) -> None:
    malformed = IdentificationRequest.model_construct(
        request_id="malformed-request",
        causal_graph={},
        edge_id="edge-1",
        method="difference-in-differences",
        assumption_ids=("assumption-1",),
        evidence_ids=("evidence-1",),
        refutation_methods=("placebo",),
    )

    monkeypatch.setattr(
        "aegis.causal.adapters.import_module",
        lambda _: pytest.fail("optional tool import must not occur for malformed input"),
    )

    with pytest.raises(CausalToolAbstention) as raised:
        DoWhyAdapter().identify(malformed)
    assert raised.value.status == IdentificationStatus.NOT_IDENTIFIED
