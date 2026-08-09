"""Deterministic point-in-time equity-universe construction.

The builder deliberately consumes supplied records rather than pretending that a small
fixture is a survivorship-free security master.  Rows unavailable at the snapshot cutoff
are discarded before revision selection, so appending future revisions cannot mutate a
historical snapshot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

from aegis.contracts._base import normalize_ticker
from aegis.contracts.quant import (
    EligibilityDecision,
    EligibilityReason,
    UniverseMember,
    UniverseSnapshot,
)
from aegis.quant_research.hashing import build_hashed

_REASON_ORDER: tuple[EligibilityReason, ...] = (
    "not_listed",
    "insufficient_liquidity",
    "insufficient_market_cap",
    "missing_sector_industry",
    "corporate_action_restricted",
    "incomplete_data",
    "borrow_unavailable",
    "outside_mandate",
)


@dataclass(frozen=True, slots=True)
class RawUniverseRecord:
    """A revision of security-master and eligibility data from a supplied source."""

    member_id: str
    ticker: str
    available_at: datetime
    listing_date: date
    delisting_date: date | None
    listing_status: str
    average_daily_dollar_volume: float
    market_cap: float
    sector: str | None
    industry: str | None
    corporate_action_status: str = "none"
    data_completeness: float = 1.0
    borrow_eligible: bool = True
    outside_mandate: bool = False
    source_ids: tuple[str, ...] = ()
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if self.listing_status not in {"listed", "halted", "delisted"}:
            raise ValueError("unsupported listing_status")
        if self.corporate_action_status not in {
            "none",
            "pending_merger",
            "pending_spinoff",
            "bankruptcy",
            "other_restricted",
        }:
            raise ValueError("unsupported corporate_action_status")
        for value, label in (
            (self.average_daily_dollar_volume, "average_daily_dollar_volume"),
            (self.market_cap, "market_cap"),
            (self.data_completeness, "data_completeness"),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.average_daily_dollar_volume < 0 or self.market_cap < 0:
            raise ValueError("liquidity and market cap cannot be negative")
        if not 0.0 <= self.data_completeness <= 1.0:
            raise ValueError("data_completeness must be in [0, 1]")
        if self.delisting_date is not None and self.delisting_date < self.listing_date:
            raise ValueError("delisting_date cannot precede listing_date")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")


@dataclass(frozen=True, slots=True)
class UniverseRules:
    """Versioned, deterministic eligibility thresholds."""

    rules_version: str
    minimum_average_daily_dollar_volume: float
    minimum_market_cap: float
    minimum_data_completeness: float
    require_sector_industry: bool = True
    require_borrow: bool = True
    restrict_corporate_actions: bool = True

    def __post_init__(self) -> None:
        if self.minimum_average_daily_dollar_volume < 0 or self.minimum_market_cap < 0:
            raise ValueError("universe thresholds cannot be negative")
        if not 0.0 <= self.minimum_data_completeness <= 1.0:
            raise ValueError("minimum_data_completeness must be in [0, 1]")


def _utc_key(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _latest_point_in_time_rows(
    records: tuple[RawUniverseRecord, ...], as_of: datetime
) -> tuple[RawUniverseRecord, ...]:
    visible = [record for record in records if record.available_at <= as_of]
    latest: dict[str, RawUniverseRecord] = {}
    for record in sorted(
        visible,
        key=lambda row: (
            row.ticker,
            _utc_key(row.available_at),
            row.revision,
            row.member_id,
            row.source_ids,
        ),
    ):
        current = latest.get(record.ticker)
        if (
            current is not None
            and record.available_at == current.available_at
            and record.revision == current.revision
            and record != current
        ):
            raise ValueError(
                f"ambiguous universe revisions for {record.ticker} at the same availability"
            )
        latest[record.ticker] = record
    return tuple(latest[ticker] for ticker in sorted(latest))


def eligibility_reasons(
    record: RawUniverseRecord, *, as_of: datetime, rules: UniverseRules
) -> tuple[EligibilityReason, ...]:
    """Return stable, exhaustive eligibility reasons in contract-defined order."""
    as_of_date = as_of.date()
    not_listed = (
        as_of_date < record.listing_date
        or (record.delisting_date is not None and as_of_date >= record.delisting_date)
        or record.listing_status in {"halted", "delisted"}
    )
    flags: dict[EligibilityReason, bool] = {
        "not_listed": not_listed,
        "insufficient_liquidity": (
            record.average_daily_dollar_volume < rules.minimum_average_daily_dollar_volume
        ),
        "insufficient_market_cap": record.market_cap < rules.minimum_market_cap,
        "missing_sector_industry": rules.require_sector_industry
        and (not record.sector or not record.industry),
        "corporate_action_restricted": rules.restrict_corporate_actions
        and record.corporate_action_status != "none",
        "incomplete_data": record.data_completeness < rules.minimum_data_completeness,
        "borrow_unavailable": rules.require_borrow and not record.borrow_eligible,
        "outside_mandate": record.outside_mandate,
    }
    reasons = tuple(reason for reason in _REASON_ORDER if flags[reason])
    return reasons or ("eligible",)


def build_universe_snapshot(
    records: tuple[RawUniverseRecord, ...],
    *,
    snapshot_id: str,
    universe_id: str,
    as_of: datetime,
    rules: UniverseRules,
    fixed_fixture: bool,
    limitation: str | None,
) -> UniverseSnapshot:
    """Build a hash-stable snapshot from only revisions visible at ``as_of``.

    A fixed fixture must state its limitation explicitly (for example, that it is not a
    survivorship-free production feed).  This is validated here and again by the contract.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if fixed_fixture and (limitation is None or not limitation.strip()):
        raise ValueError("fixed universe fixtures require an explicit limitation")
    if not fixed_fixture and limitation is not None:
        raise ValueError("non-fixture universes cannot have a fixture limitation")
    selected = _latest_point_in_time_rows(records, as_of)
    if not selected:
        raise ValueError("no universe records were available at as_of")

    members: list[UniverseMember] = []
    decisions: list[EligibilityDecision] = []
    for record in selected:
        # Keep the survivor-state identifier explicit for static and dynamic leakage gates.
        trading_status = record.listing_status
        member = build_hashed(
            UniverseMember,
            member_id=record.member_id,
            ticker=record.ticker,
            listing_status=trading_status,
            average_daily_dollar_volume=record.average_daily_dollar_volume,
            market_cap=record.market_cap,
            sector=record.sector,
            industry=record.industry,
            corporate_action_status=record.corporate_action_status,
            data_completeness=record.data_completeness,
            borrow_eligible=record.borrow_eligible,
            source_ids=record.source_ids,
            as_of=as_of,
            available_at=record.available_at,
        )
        reasons = eligibility_reasons(record, as_of=as_of, rules=rules)
        ticker_slug = record.ticker.lower().replace(".", "-").replace("--", "-")
        decision = build_hashed(
            EligibilityDecision,
            decision_id=f"eligibility-{ticker_slug}-v1",
            member_id=record.member_id,
            ticker=record.ticker,
            eligible=reasons == ("eligible",),
            reasons=reasons,
            rules_version=rules.rules_version,
            as_of=as_of,
            available_at=record.available_at,
        )
        members.append(member)
        decisions.append(decision)

    return build_hashed(
        UniverseSnapshot,
        snapshot_id=snapshot_id,
        universe_id=universe_id,
        as_of=as_of,
        members=tuple(members),
        decisions=tuple(decisions),
        fixed_fixture=fixed_fixture,
        limitation=limitation,
    )
