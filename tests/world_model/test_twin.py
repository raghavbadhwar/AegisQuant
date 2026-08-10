from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from aegis.world_model.contracts import VariableProvenance, WorldSnapshot, WorldVariable
from aegis.world_model.twin import InvariantViolation, TwinState, TwinTransition

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _variable() -> WorldVariable:
    return WorldVariable(
        variable_id="hyperscaler.ai_capex_growth",
        value=0.2,
        unit="ratio",
        provenance=VariableProvenance.OBSERVED,
        available_at=NOW,
        evidence_ids=("evidence-1",),
        uncertainty_label="empirical",
    )


def _snapshot() -> WorldSnapshot:
    return WorldSnapshot(
        snapshot_id="world-snapshot-1",
        as_of=NOW,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash="b" * 64,
        variables=(_variable(),),
        random_seed=42,
        code_revision="test-revision",
    ).sealed()


def _state(**updates: object) -> TwinState:
    snapshot = _snapshot()
    assert snapshot.content_hash is not None
    values: dict[str, object] = {
        "state_id": "company-state-1",
        "twin_id": "company-twin-1",
        "domain_pack_id": "ai-infrastructure",
        "domain_pack_version": "1.0.0",
        "world_snapshot_hash": snapshot.content_hash,
        "world_snapshot": snapshot,
        "as_of": NOW,
        "variables": (_variable(),),
    }
    values.update(updates)
    return TwinState(**values)


def test_twin_state_seals_deterministically() -> None:
    state = _state()

    sealed = state.sealed()

    assert sealed.content_hash is not None
    assert sealed.sealed().content_hash == sealed.content_hash
    assert TwinState(**sealed.model_dump()).content_hash == sealed.content_hash


def test_twin_state_rejects_variable_unavailable_at_as_of() -> None:
    with pytest.raises(ValueError, match="future"):
        _state(
            variables=(
                _variable().model_copy(update={"available_at": datetime(2024, 1, 2, tzinfo=UTC)}),
            ),
        )


def test_twin_state_rejects_observed_data_after_its_bound_source_snapshot() -> None:
    snapshot = _snapshot()
    assert snapshot.content_hash is not None
    future_observed = _variable().model_copy(
        update={"available_at": datetime(2024, 1, 2, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="source world snapshot"):
        TwinState(
            state_id="company-state-2",
            twin_id="company-twin-1",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
            world_snapshot_hash=snapshot.content_hash,
            world_snapshot=snapshot,
            as_of=datetime(2024, 1, 2, tzinfo=UTC),
            variables=(future_observed,),
        )


def test_twin_state_rejects_duplicate_variable_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        _state(variables=(_variable(), _variable()))


def test_invariant_violation_rejects_order_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        InvariantViolation(
            violation_id="cash-nonnegative-1",
            invariant_id="cash-nonnegative",
            twin_id="company-twin-1",
            state_id="company-state-1",
            severity="error",
            message="candidate state violates the cash constraint",
            affected_variable_ids=("cash",),
            order_id="forbidden-order",
        )


def test_twin_transition_requires_result_state_domain_binding() -> None:
    other_domain_state = _state(
        state_id="company-state-2",
        domain_pack_id="semiconductor-equipment",
    )

    with pytest.raises(ValueError, match="domain pack"):
        TwinTransition(
            transition_id="company-transition-1",
            twin_id="company-twin-1",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
            from_state_id="company-state-1",
            from_state=_state(),
            to_state=other_domain_state,
            parameter_draw_id="draw-1",
            time_step=timedelta(days=1),
            support_ids=("mechanism-1",),
        )


def test_twin_transition_requires_result_state_version_binding() -> None:
    other_version_state = _state(
        state_id="company-state-2",
        domain_pack_version="2.0.0",
    )

    with pytest.raises(ValueError, match="version"):
        TwinTransition(
            transition_id="company-transition-1",
            twin_id="company-twin-1",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
            from_state_id="company-state-1",
            from_state=_state(),
            to_state=other_version_state,
            parameter_draw_id="draw-1",
            time_step=timedelta(days=1),
            support_ids=("mechanism-1",),
        )


def test_twin_transition_seals_deterministically() -> None:
    state = _state(state_id="company-state-2", as_of=NOW + timedelta(days=1))
    transition = TwinTransition(
        transition_id="company-transition-1",
        twin_id="company-twin-1",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        from_state_id="company-state-1",
        from_state=_state(),
        to_state=state,
        parameter_draw_id="draw-1",
        time_step=timedelta(days=1),
        support_ids=("mechanism-1",),
    )

    sealed = transition.sealed()

    assert sealed.content_hash is not None
    assert sealed.sealed().content_hash == sealed.content_hash
    assert TwinTransition(**sealed.model_dump()).content_hash == sealed.content_hash


def test_twin_transition_requires_the_declared_source_state_and_time_advance() -> None:
    source_state = _state()
    target_state = _state(
        state_id="company-state-2",
        as_of=NOW + timedelta(days=1),
    )

    with pytest.raises(ValueError, match="source state"):
        TwinTransition(
            transition_id="company-transition-2",
            twin_id="company-twin-1",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
            from_state_id="different-state",
            from_state=source_state,
            to_state=target_state,
            parameter_draw_id="draw-1",
            time_step=timedelta(days=1),
            support_ids=("mechanism-1",),
        )


def test_twin_transition_rejects_a_result_without_the_declared_time_advance() -> None:
    source_state = _state()
    target_state = _state(state_id="company-state-2")

    with pytest.raises(ValueError, match="declared time step"):
        TwinTransition(
            transition_id="company-transition-3",
            twin_id="company-twin-1",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
            from_state_id=source_state.state_id,
            from_state=source_state,
            to_state=target_state,
            parameter_draw_id="draw-1",
            time_step=timedelta(days=1),
            support_ids=("mechanism-1",),
        )


def test_digital_twin_protocol_is_structural_and_candidate_only() -> None:
    import aegis.world_model.twin as twin_module

    class Adapter:
        twin_id = "company-twin-1"

        def initial_state(self, snapshot: object) -> TwinState:
            raise NotImplementedError

        def transition(
            self,
            state: TwinState,
            inputs: Mapping[str, float],
            parameter_draw_id: str,
            time_step: timedelta,
        ) -> TwinTransition:
            raise NotImplementedError

        def observe(self, state: TwinState) -> Mapping[str, float]:
            raise NotImplementedError

        def validate(self, state: TwinState) -> tuple[InvariantViolation, ...]:
            raise NotImplementedError

    assert isinstance(Adapter(), twin_module.DigitalTwin)
