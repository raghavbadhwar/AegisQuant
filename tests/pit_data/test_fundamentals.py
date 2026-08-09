from datetime import UTC, datetime

from aegis.pit_data import fundamentals_as_of, normalize_sec_facts
from aegis.pit_data.sec import SecFactObservation


def test_restatement_is_not_visible_before_its_publication() -> None:
    initial = SecFactObservation(
        cik="0000320193",
        taxonomy="us-gaap",
        tag="Revenue",
        unit="USD",
        value=10.0,
        form="10-Q",
        accession_number="0000320193-21-000001",
        period_end=datetime(2021, 6, 30, tzinfo=UTC),
        filed_at=datetime(2021, 8, 10, tzinfo=UTC),
        available_at=datetime(2021, 8, 10, tzinfo=UTC),
    )
    amended = initial.model_copy(
        update={
            "value": 9.6,
            "form": "10-Q/A",
            "accession_number": "0000320193-22-000001",
            "filed_at": datetime(2022, 2, 17, tzinfo=UTC),
            "available_at": datetime(2022, 2, 17, tzinfo=UTC),
        }
    )
    facts = normalize_sec_facts("AAPL", (initial, amended))
    assert [
        item.value for item in fundamentals_as_of(facts, datetime(2021, 12, 1, tzinfo=UTC))
    ] == [10.0]
    assert [item.value for item in fundamentals_as_of(facts, datetime(2022, 3, 1, tzinfo=UTC))] == [
        9.6
    ]
