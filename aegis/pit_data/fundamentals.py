"""SEC fact normalization preserving reported revisions rather than overwriting history."""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .sec import SecFactObservation


class PITFundamentalFact(BaseModel):
    """Normalized fundamental fact version bound to its original SEC accession."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(min_length=1)
    taxonomy: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    value: float
    period_end: AwareDatetime
    filed_at: AwareDatetime
    available_at: AwareDatetime
    form: str = Field(min_length=1)
    accession: str = Field(min_length=1)
    raw_artifact_id: str = Field(min_length=1)


def normalize_sec_facts(
    entity_id: str, observations: tuple[SecFactObservation, ...]
) -> tuple[PITFundamentalFact, ...]:
    """Keep all observations: later amendments deliberately do not mutate old values."""
    return tuple(
        sorted(
            (
                PITFundamentalFact(
                    entity_id=entity_id,
                    taxonomy=item.taxonomy,
                    concept=item.tag,
                    unit=item.unit,
                    value=item.value,
                    period_end=item.period_end,
                    filed_at=item.filed_at,
                    available_at=item.available_at,
                    form=item.form,
                    accession=item.accession_number,
                    raw_artifact_id=f"sec:{item.cik}:{item.accession_number}",
                )
                for item in observations
            ),
            key=lambda item: (item.available_at, item.accession, item.concept),
        )
    )


def fundamentals_as_of(
    facts: tuple[PITFundamentalFact, ...], at: datetime
) -> tuple[PITFundamentalFact, ...]:
    """Return the newest public version for each concept/unit/reporting period at cutoff."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("fundamental as-of cutoff must be timezone-aware")
    versions: dict[tuple[str, str, str, str, datetime], PITFundamentalFact] = {}
    for item in facts:
        if item.available_at > at:
            continue
        key = (item.entity_id, item.taxonomy, item.concept, item.unit, item.period_end)
        previous = versions.get(key)
        if previous is None or (item.available_at, item.accession) > (
            previous.available_at,
            previous.accession,
        ):
            versions[key] = item
    return tuple(
        sorted(versions.values(), key=lambda item: (item.entity_id, item.concept, item.period_end))
    )
