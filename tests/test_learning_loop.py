import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import aegisquant.case_cli as case_cli
from aegisquant.case_cli import main
from aegisquant.contracts.learning import LearningEvaluationV2
from aegisquant.contracts.research import MarketBar
from aegisquant.contracts.risk import OrderIntent, OrderSide, OrderType, TimeInForce
from aegisquant.fixture_case import FixtureCaseSpec
from aegisquant.learning.governance import (
    approve_candidate,
    approve_candidate_v2,
    evaluate_candidate,
    evaluate_candidate_v2,
)
from aegisquant.learning.loop import (
    apply_approved_strategy_candidate,
    propose_candidate,
    verify_approved_candidate,
)
from aegisquant.quant.multi_period import (
    MultiPeriodCaseReport,
    MultiPeriodCaseSpec,
    RebalancePeriod,
    multi_period_holdout_digest,
    run_multi_period_case,
    verify_multi_period_report,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.security.learning_attestation import (
    LearningAttestationError,
    LearningAttestationSigner,
    LearningAttestationVerifier,
    TrustedLearningKey,
)

NOW = datetime(2026, 2, 1, tzinfo=UTC)
SOURCE_CASE_ID = UUID("00000000-0000-0000-0000-000000000301")
FIXTURE = Path("data/fixtures/cases/multi_asset_control.json")
SHORT_FIXTURE = Path("data/fixtures/cases/multi_period_control.json")


def sha(character: str) -> str:
    return "sha256:" + character * 64


def baseline() -> FixtureCaseSpec:
    return FixtureCaseSpec.model_validate_json(FIXTURE.read_bytes())


@lru_cache
def verified_source() -> tuple[MultiPeriodCaseSpec, MultiPeriodCaseReport]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    periods: list[RebalancePeriod] = []
    bars = [
        MarketBar(
            instrument_id=instrument,
            instrument_version=f"{instrument.lower()}-v1",
            observed_at=start - timedelta(hours=17),
            available_at=start - timedelta(hours=17),
            tradable_at=start - timedelta(hours=17),
            open_price=price,
            close_price=price,
            volume=Decimal("1000"),
            currency="USD",
        )
        for instrument, price in (("AAA", Decimal("10")), ("BENCH", Decimal("100")))
    ]
    for index in range(30):
        decision_at = start + timedelta(days=index, hours=9)
        fill_at = start + timedelta(days=index, hours=10)
        orders = (
            (
                OrderIntent(
                    client_order_id="learn-buy-aaa",
                    instrument_id="AAA",
                    instrument_version="aaa-v1",
                    venue_id="fixture-venue",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                    quantity=Decimal("1"),
                    currency="USD",
                ),
            )
            if index == 0
            else ()
        )
        periods.append(
            RebalancePeriod(
                period_id=f"learning-period-{index + 1}",
                decision_at=decision_at,
                fill_at=fill_at,
                orders=orders,
            )
        )
        aaa = Decimal(10 + index) + (Decimal("0.5") if index % 2 else Decimal("-0.25"))
        bench = Decimal(100 + index)
        for instrument, price in (("AAA", aaa), ("BENCH", bench)):
            bars.append(
                MarketBar(
                    instrument_id=instrument,
                    instrument_version=f"{instrument.lower()}-v1",
                    observed_at=fill_at - timedelta(minutes=30),
                    available_at=fill_at - timedelta(minutes=30),
                    tradable_at=fill_at,
                    open_price=price,
                    close_price=price,
                    volume=Decimal("1000"),
                    currency="USD",
                )
            )
    period_tuple = tuple(periods)
    bar_tuple = tuple(bars)
    holdout_ids = tuple(item.period_id for item in period_tuple[-5:])
    holdout = tuple(item for item in period_tuple if item.period_id in set(holdout_ids))
    spec = MultiPeriodCaseSpec(
        tenant_id="tenant-fixture",
        case_id=SOURCE_CASE_ID,
        initial_cash=Decimal("1000"),
        transaction_cost_rate=Decimal("0.001"),
        max_bar_age_seconds=100_000,
        benchmark_instrument_id="BENCH",
        bars=bar_tuple,
        periods=period_tuple,
        holdout_period_ids=holdout_ids,
        locked_holdout_digest=multi_period_holdout_digest(
            holdout_periods=holdout,
            bars=bar_tuple,
            corporate_actions=(),
            transaction_cost_rate=Decimal("0.001"),
            max_bar_age_seconds=100_000,
            benchmark_instrument_id="BENCH",
        ),
        walk_forward_training_periods=10,
        walk_forward_test_periods=5,
        walk_forward_step=5,
    )
    report = run_multi_period_case(spec)
    assert report.performance.sufficient_evidence
    assert verify_multi_period_report(spec, report)
    return spec, report


def proposal_inputs() -> dict[str, object]:
    source_spec, source_report = verified_source()
    return {
        "source_spec": source_spec,
        "source_report": source_report,
        "baseline_spec": baseline(),
        "candidate_id": "candidate-uncertainty-floor-v2",
        "source_actor_id": "strategy-owner",
        "independent_evaluator_id": "independent-evaluator",
        "evaluation_plan_digest": sha("3"),
        "rollback_manifest_digest": sha("4"),
        "strategy_parameter": "portfolio_policy.uncertainty_floor",
        "proposed_value": Decimal("0.02"),
        "now": NOW,
        "candidate_matures_at": NOW + timedelta(days=30),
    }


def test_learning_cycle_abstains_for_unverified_insufficient_or_immature_outcome() -> None:
    _, source_report = verified_source()
    tampered_report = source_report.model_copy(update={"report_digest": sha("9")})
    assert (
        propose_candidate(**(proposal_inputs() | {"source_report": tampered_report})).reason_code
        == "OUTCOME_UNVERIFIED"
    )

    short_spec = MultiPeriodCaseSpec.model_validate_json(SHORT_FIXTURE.read_bytes())
    short_report = run_multi_period_case(short_spec)
    assert (
        propose_candidate(
            **(proposal_inputs() | {"source_spec": short_spec, "source_report": short_report})
        ).reason_code
        == "INSUFFICIENT_EVIDENCE"
    )

    assert (
        propose_candidate(
            **(
                proposal_inputs()
                | {"now": source_report.periods[-1].fill_at - timedelta(seconds=1)}
            )
        ).reason_code
        == "OUTCOME_IMMATURE"
    )
    assert (
        propose_candidate(
            **(proposal_inputs() | {"independent_evaluator_id": "strategy-owner"})
        ).reason_code
        == "EVALUATION_NOT_INDEPENDENT"
    )


def candidate_and_proposal() -> tuple[object, object]:
    result = propose_candidate(**proposal_inputs())
    assert result.candidate is not None
    assert result.proposal is not None
    assert result.outcome == "CANDIDATE"
    assert result.candidate.source_manifest_digest == digest_canonical(result.proposal)
    return result.candidate, result.proposal


def approved_artifacts() -> tuple[object, object, LearningEvaluationV2, object]:
    candidate, proposal = candidate_and_proposal()
    evaluation = evaluate_candidate_v2(
        candidate,
        proposal,
        evaluator_id="independent-evaluator",
        evaluation_manifest_digest=sha("3"),
        shadow_passed=True,
        canary_passed=True,
        now=NOW + timedelta(days=30),
    )
    approval = approve_candidate_v2(
        candidate,
        proposal,
        evaluation,
        approver_id="human-governance-owner",
        approver_is_human=True,
        rollback_manifest_digest=sha("4"),
        now=NOW + timedelta(days=30, seconds=1),
        expires_at=NOW + timedelta(days=60),
    )
    return candidate, proposal, evaluation, approval


def attested_artifacts() -> tuple[object, object, object, object, LearningAttestationVerifier]:
    candidate, proposal, evaluation, approval = approved_artifacts()
    evaluator_key = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)
    approver_key = Ed25519PrivateKey.from_private_bytes(b"\x22" * 32)
    verifier = LearningAttestationVerifier(
        {
            "learning-evaluator-1": TrustedLearningKey(
                public_key=evaluator_key.public_key(),
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=365),
                actor_id="independent-evaluator",
                tenant_id="tenant-fixture",
                allowed_roles=frozenset({"EVALUATOR"}),
            ),
            "learning-human-1": TrustedLearningKey(
                public_key=approver_key.public_key(),
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=365),
                actor_id="human-governance-owner",
                tenant_id="tenant-fixture",
                allowed_roles=frozenset({"HUMAN_APPROVER"}),
            ),
        }
    )
    return (
        candidate,
        proposal,
        LearningAttestationSigner("learning-evaluator-1", evaluator_key).sign_evaluation(
            evaluation
        ),
        LearningAttestationSigner("learning-human-1", approver_key).sign_approval(approval),
        verifier,
    )


def test_verified_outcome_creates_exact_bound_candidate() -> None:
    source_spec, source_report = verified_source()
    candidate, proposal = candidate_and_proposal()

    assert candidate.case_id == baseline().manifest.case_id == proposal.case_id
    assert proposal.source_case_id == source_spec.case_id
    assert proposal.source_outcome_digest == digest_canonical(source_report)
    assert proposal.baseline_digest == digest_canonical(baseline())
    assert proposal.locked_holdout_digest == source_spec.locked_holdout_digest
    assert proposal.evaluation_plan_digest == sha("3")
    assert proposal.rollback_manifest_digest == sha("4")


def test_v1_learning_api_and_json_contract_remain_compatible() -> None:
    candidate, _ = candidate_and_proposal()
    evaluation = evaluate_candidate(
        candidate,
        evaluator_id="legacy-evaluator",
        evaluation_manifest_digest=sha("3"),
        shadow_passed=True,
        canary_passed=True,
        now=candidate.matures_at,
    )
    approval = approve_candidate(
        candidate,
        evaluation,
        approver_id="legacy-approver",
        approval_digest=sha("6"),
        rollback_manifest_digest=sha("4"),
        now=candidate.matures_at,
    )

    assert type(evaluation).model_validate_json(evaluation.model_dump_json()) == evaluation
    assert type(approval).model_validate_json(approval.model_dump_json()) == approval


@pytest.mark.parametrize(
    ("evaluation_change", "approval_change"),
    [
        ({"tenant_id": "tenant-other"}, {}),
        ({"case_id": UUID("00000000-0000-0000-0000-000000000999")}, {}),
        ({"candidate_id": "candidate-other"}, {}),
        ({"evaluation_manifest_digest": sha("9")}, {}),
        ({"proposal_manifest_digest": sha("9")}, {}),
        ({"shadow_passed": False}, {}),
        ({"canary_passed": False}, {}),
        ({}, {"rollback_manifest_digest": sha("9")}),
        ({}, {"approver_is_human": False}),
    ],
)
def test_approval_rejects_every_unbound_or_unapproved_artifact(
    evaluation_change: dict[str, object], approval_change: dict[str, object]
) -> None:
    candidate, proposal = candidate_and_proposal()
    evaluation = evaluate_candidate_v2(
        candidate,
        proposal,
        evaluator_id="independent-evaluator",
        evaluation_manifest_digest=sha("3"),
        shadow_passed=True,
        canary_passed=True,
        now=NOW + timedelta(days=30),
    ).model_copy(update=evaluation_change)
    approval_arguments: dict[str, object] = {
        "approver_id": "human-governance-owner",
        "approver_is_human": True,
        "rollback_manifest_digest": sha("4"),
        "now": NOW + timedelta(days=30, seconds=1),
        "expires_at": NOW + timedelta(days=60),
    }

    with pytest.raises(ValueError):
        approve_candidate_v2(
            candidate,
            proposal,
            evaluation,
            **(approval_arguments | approval_change),
        )


def test_only_exact_approved_allowlisted_parameter_can_change_later_fixture() -> None:
    candidate, proposal, signed_evaluation, signed_approval, verifier = attested_artifacts()
    source = baseline()
    source_spec, source_report = verified_source()

    updated = apply_approved_strategy_candidate(
        source,
        candidate=candidate,
        proposal=proposal,
        signed_evaluation=signed_evaluation,
        signed_approval=signed_approval,
        source_spec=source_spec,
        source_report=source_report,
        attestation_verifier=verifier,
        now=NOW + timedelta(days=31),
    )

    expected = source.model_dump(mode="python")
    expected["portfolio_policy"]["uncertainty_floor"] = Decimal("0.02")
    assert updated.model_dump(mode="python") == expected
    assert updated.risk_policy == source.risk_policy
    assert updated.manifest == source.manifest
    assert updated.snapshot == source.snapshot

    tampered_approval = signed_approval.model_copy(
        update={
            "payload": signed_approval.payload.model_copy(update={"evaluation_digest": sha("9")})
        }
    )
    with pytest.raises(LearningAttestationError, match="signature"):
        verify_approved_candidate(
            candidate,
            proposal,
            signed_evaluation,
            tampered_approval,
            source_spec=source_spec,
            source_report=source_report,
            attestation_verifier=verifier,
            now=NOW + timedelta(days=31),
        )
    with pytest.raises(ValueError, match="baseline"):
        apply_approved_strategy_candidate(
            source.model_copy(
                update={
                    "portfolio_policy": source.portfolio_policy.model_copy(
                        update={"uncertainty_floor": Decimal("0.03")}
                    )
                }
            ),
            candidate=candidate,
            proposal=proposal,
            signed_evaluation=signed_evaluation,
            signed_approval=signed_approval,
            source_spec=source_spec,
            source_report=source_report,
            attestation_verifier=verifier,
            now=NOW + timedelta(days=31),
        )


def test_evaluator_key_cannot_forge_human_promotion_approval() -> None:
    candidate, proposal, signed_evaluation, signed_approval, verifier = attested_artifacts()
    evaluator_key = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)
    forged = LearningAttestationSigner("learning-evaluator-1", evaluator_key).sign_approval(
        signed_approval.payload
    )
    source_spec, source_report = verified_source()

    with pytest.raises(LearningAttestationError, match="scope"):
        verify_approved_candidate(
            candidate,
            proposal,
            signed_evaluation,
            forged,
            source_spec=source_spec,
            source_report=source_report,
            attestation_verifier=verifier,
            now=NOW + timedelta(days=31),
        )


def test_expired_approval_cannot_authorize_application() -> None:
    candidate, proposal, signed_evaluation, signed_approval, verifier = attested_artifacts()
    source_spec, source_report = verified_source()

    with pytest.raises(LearningAttestationError, match="validity window"):
        verify_approved_candidate(
            candidate,
            proposal,
            signed_evaluation,
            signed_approval,
            source_spec=source_spec,
            source_report=source_report,
            attestation_verifier=verifier,
            now=signed_approval.payload.expires_at,
        )


@pytest.mark.parametrize("inactive", ["expired", "revoked"])
def test_backdated_approval_from_now_inactive_key_is_rejected(inactive: str) -> None:
    candidate, proposal, signed_evaluation, signed_approval, _ = attested_artifacts()
    evaluator_key = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)
    approver_key = Ed25519PrivateKey.from_private_bytes(b"\x22" * 32)
    inactive_at = signed_approval.payload.approved_at + timedelta(seconds=1)
    verifier = LearningAttestationVerifier(
        {
            "learning-evaluator-1": TrustedLearningKey(
                public_key=evaluator_key.public_key(),
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=365),
                actor_id="independent-evaluator",
                tenant_id="tenant-fixture",
                allowed_roles=frozenset({"EVALUATOR"}),
            ),
            "learning-human-1": TrustedLearningKey(
                public_key=approver_key.public_key(),
                valid_from=NOW - timedelta(days=1),
                valid_until=(inactive_at if inactive == "expired" else NOW + timedelta(days=365)),
                actor_id="human-governance-owner",
                tenant_id="tenant-fixture",
                allowed_roles=frozenset({"HUMAN_APPROVER"}),
                revoked_at=inactive_at if inactive == "revoked" else None,
            ),
        }
    )
    source_spec, source_report = verified_source()

    with pytest.raises(LearningAttestationError, match="scope"):
        verify_approved_candidate(
            candidate,
            proposal,
            signed_evaluation,
            signed_approval,
            source_spec=source_spec,
            source_report=source_report,
            attestation_verifier=verifier,
            now=NOW + timedelta(days=31),
        )


def test_learning_cli_records_lifecycle_without_running_a_fixture_case(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        case_cli,
        "run_fixture_case",
        lambda _: (_ for _ in ()).throw(AssertionError("learning command ran a fixture case")),
    )

    def write(name: str, value: dict[str, object]) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return path

    inputs = {
        key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        for key, value in proposal_inputs().items()
    }
    inputs["proposed_value"] = str(inputs["proposed_value"])
    inputs["now"] = inputs["now"].isoformat()
    inputs["candidate_matures_at"] = inputs["candidate_matures_at"].isoformat()
    propose_path = write("propose.json", inputs)
    assert main(("learning", "propose", str(propose_path))) == 0
    cycle = json.loads(capsys.readouterr().out)

    evaluate_path = write(
        "evaluate.json",
        {
            "candidate": cycle["candidate"],
            "proposal": cycle["proposal"],
            "evaluator_id": "independent-evaluator",
            "evaluation_manifest_digest": sha("3"),
            "shadow_passed": True,
            "canary_passed": True,
            "now": (NOW + timedelta(days=30)).isoformat(),
        },
    )
    assert main(("learning", "evaluate", str(evaluate_path))) == 0
    evaluation = json.loads(capsys.readouterr().out)

    approve_path = write(
        "approve.json",
        {
            "candidate": cycle["candidate"],
            "proposal": cycle["proposal"],
            "evaluation": evaluation,
            "approver_id": "human-governance-owner",
            "approver_is_human": True,
            "rollback_manifest_digest": sha("4"),
            "now": (NOW + timedelta(days=30, seconds=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=60)).isoformat(),
        },
    )
    assert main(("learning", "approve", str(approve_path))) == 0
    approval = json.loads(capsys.readouterr().out)
    assert approval["approver_kind"] == "HUMAN"

    source_spec, source_report = verified_source()
    verify_path = write(
        "verify.json",
        {
            "candidate": cycle["candidate"],
            "proposal": cycle["proposal"],
            "evaluation": evaluation,
            "approval": approval,
            "source_spec": source_spec.model_dump(mode="json"),
            "source_report": source_report.model_dump(mode="json"),
        },
    )
    assert main(("learning", "verify", str(verify_path))) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified == {
        "structurally_verified": True,
        "promotion_authorized": False,
        "proposal": cycle["proposal"],
    }
