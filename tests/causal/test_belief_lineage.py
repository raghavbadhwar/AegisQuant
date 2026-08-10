from datetime import UTC, datetime, timedelta

import pytest

from aegis.causal import BeliefRevision, BeliefRevisionLedger

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_belief_revisions_are_append_only_and_bind_each_predecessor_hash() -> None:
    root = BeliefRevision(
        revision_id="capex-belief-1",
        belief_id="capex-demand",
        sequence=1,
        as_of=NOW,
        prior_probability=0.5,
        posterior_probability=0.5,
        assumption_ids=("candidate-prior",),
    ).sealed()
    ledger = BeliefRevisionLedger(revisions=(root,)).sealed()
    successor = BeliefRevision(
        revision_id="capex-belief-2",
        belief_id="capex-demand",
        sequence=2,
        as_of=NOW + timedelta(days=1),
        prior_probability=0.5,
        posterior_probability=0.6,
        evidence_ids=("evidence-1",),
        assumption_ids=("candidate-prior",),
        parent_revision_hash=root.content_hash,
    ).sealed()

    updated = ledger.append(successor)

    assert updated.revisions[-1].content_hash == successor.content_hash
    invalid_payload = successor.model_dump(mode="json", exclude={"content_hash"})
    invalid_payload["parent_revision_hash"] = "a" * 64
    invalid_successor = BeliefRevision.model_validate(invalid_payload).sealed()
    with pytest.raises(ValueError, match="parent revision hash"):
        ledger.append(invalid_successor)
