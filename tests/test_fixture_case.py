import json
from pathlib import Path

import pytest

from aegisquant.fixture_case import FixtureCaseSpec, main, run_fixture_case

FIXTURE = Path("data/fixtures/cases/multi_asset_control.json")


def test_fixture_case_is_complete_reconciled_and_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = FixtureCaseSpec.model_validate_json(FIXTURE.read_bytes())
    first = run_fixture_case(spec)
    second = run_fixture_case(spec)

    assert first == second
    assert len(first.fills) == 2
    assert first.reconciled
    assert first.ledger_verified
    assert first.ledger_event_count == 6
    assert first.performance.observations == 1
    assert not first.performance.sufficient_evidence

    assert main((str(FIXTURE),)) == 0
    assert json.loads(capsys.readouterr().out) == first.model_dump(mode="json")


def test_fixture_case_rejects_tampered_market_data() -> None:
    raw = json.loads(FIXTURE.read_text())
    for market_bar in raw["bars"]:
        if market_bar["available_at"] == "2026-01-03T00:00:00Z":
            market_bar["observed_at"] = "2026-01-02T00:00:00Z"
            market_bar["available_at"] = "2026-01-02T00:00:00Z"
    with pytest.raises(ValueError, match="snapshot content"):
        FixtureCaseSpec.model_validate_json(json.dumps(raw))

    raw = json.loads(FIXTURE.read_text())
    raw["forecasts"][0]["expected_return"] = "0.11"
    with pytest.raises(ValueError, match="snapshot content"):
        FixtureCaseSpec.model_validate_json(json.dumps(raw))


def test_fixture_case_requires_an_exact_bound_snapshot() -> None:
    raw = json.loads(FIXTURE.read_text())
    raw.pop("snapshot", None)
    with pytest.raises(ValueError, match="snapshot"):
        FixtureCaseSpec.model_validate_json(json.dumps(raw))
