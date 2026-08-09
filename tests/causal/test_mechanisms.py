import pytest

from aegis.causal import MechanismDefinition


def candidate(**update: object) -> MechanismDefinition:
    values: dict[str, object] = {
        "mechanism_id": "m-1",
        "causal_edge_id": "e-1",
        "domain_pack": "ai-infrastructure-v1",
        "input_variable_ids": ("capex",),
        "output_variable_ids": ("revenue",),
        "assumption_ids": ("demand-holds",),
    }
    values.update(update)
    return MechanismDefinition(**values)


def test_mechanism_cannot_be_execution_authority() -> None:
    with pytest.raises(ValueError, match="authority"):
        candidate(authority="execution")


def test_validated_mechanism_requires_evidence_and_cases() -> None:
    with pytest.raises(ValueError, match="evidence"):
        candidate(status="validated")
    assert (
        candidate(
            status="validated", evidence_ids=("ev-1",), validation_case_ids=("case-1",)
        ).status
        == "validated"
    )
