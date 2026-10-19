from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from aegis.contracts import ResearchCase
from aegis.data import FixtureDataClient
from aegis.quant.models import DeterministicCompositeProvider

ROOT = Path(__file__).resolve().parents[2]


class CountingDataClient(FixtureDataClient):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.snapshot_calls = 0

    def latest_snapshot(self, tickers, as_of):  # type: ignore[no-untyped-def]
        self.snapshot_calls += 1
        return super().latest_snapshot(tickers, as_of)


def test_deterministic_provider_reuses_supplied_cycle_snapshot() -> None:
    payload = json.loads((ROOT / "data/fixtures/cases/nvda_earnings_case.json").read_text())
    case = ResearchCase(
        case_id=payload["case_id"],
        research_question=payload["research_question"],
        tickers=payload["tickers"],
        as_of=datetime.fromisoformat(payload["as_of"]),
        horizon_days=payload["horizon_days"],
        mode="historical",
        created_at=datetime.fromisoformat(payload["created_at"]),
    )
    client = CountingDataClient(ROOT / "data/fixtures")
    snapshot = client.latest_snapshot(case.tickers, case.as_of)
    dossier = DeterministicCompositeProvider(client).research(case, snapshot)
    assert client.snapshot_calls == 1
    assert dossier.evidence.records
    assert dossier.forecasts
