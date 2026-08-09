"""Immutable factor registry and point-in-time representative factor calculations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aegis.contracts._base import normalize_ticker
from aegis.contracts.quant import FactorDefinition, FactorObservation, UniverseSnapshot
from aegis.quant_research.hashing import build_hashed

_VERSIONED_ID = re.compile(r"^(?P<name>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)-v(?P<version>[1-9][0-9]*)$")


class DuplicateFactorError(ValueError):
    """Raised when a factor ID/version is already present in a registry."""


class FactorInputUnavailable(ValueError):
    """Raised when strict evaluation cannot calculate every eligible member."""


@dataclass(frozen=True, slots=True)
class FactorInputRecord:
    """One point-in-time revision of a factor input.

    ``observed_at`` is the economic timestamp and ``available_at`` is when this revision
    became knowable.  Both must pass the factor's lag cutoff before the row can be used.
    """

    ticker: str
    field: str
    value: float
    observed_at: datetime
    available_at: datetime
    revision: int = 1
    source_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        if not self.field.strip():
            raise ValueError("factor input field cannot be empty")
        if not math.isfinite(self.value):
            raise ValueError("factor input value must be finite")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        if self.revision < 1:
            raise ValueError("revision must be positive")


@dataclass(frozen=True, slots=True)
class FactorAbstention:
    ticker: str
    reason: str


@dataclass(frozen=True, slots=True)
class FactorRun:
    observations: tuple[FactorObservation, ...]
    abstentions: tuple[FactorAbstention, ...]

    @property
    def complete(self) -> bool:
        return not self.abstentions


@dataclass(frozen=True, slots=True)
class FactorRegistry:
    """An immutable registry keyed by the semantic factor ID and version."""

    definitions: tuple[FactorDefinition, ...] = ()

    def __post_init__(self) -> None:
        seen: set[tuple[str, int]] = set()
        for definition in self.definitions:
            key = _factor_key(definition.factor_id)
            if key in seen:
                raise DuplicateFactorError(f"duplicate factor ID/version: {definition.factor_id}")
            seen.add(key)

    def register(self, definition: FactorDefinition) -> FactorRegistry:
        """Return a new registry; never mutate the existing registry."""
        key = _factor_key(definition.factor_id)
        if any(_factor_key(item.factor_id) == key for item in self.definitions):
            raise DuplicateFactorError(f"duplicate factor ID/version: {definition.factor_id}")
        ordered = tuple(
            sorted((*self.definitions, definition), key=lambda item: _factor_key(item.factor_id))
        )
        return FactorRegistry(ordered)

    def add(self, definition: FactorDefinition) -> FactorRegistry:
        """Alias for ``register`` for callers that use collection terminology."""
        return self.register(definition)

    def get(self, factor_id: str) -> FactorDefinition:
        matches = [item for item in self.definitions if item.factor_id == factor_id]
        if not matches:
            raise KeyError(factor_id)
        return matches[0]

    def versions(self, factor_name: str) -> tuple[FactorDefinition, ...]:
        matches = [
            item for item in self.definitions if _factor_key(item.factor_id)[0] == factor_name
        ]
        return tuple(sorted(matches, key=lambda item: _factor_key(item.factor_id)[1]))


def _factor_key(factor_id: str) -> tuple[str, int]:
    match = _VERSIONED_ID.fullmatch(factor_id)
    if match is None:
        raise ValueError(f"factor_id is not versioned: {factor_id}")
    return match.group("name"), int(match.group("version"))


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _visible_revisions(
    inputs: tuple[FactorInputRecord, ...], *, cutoff: datetime
) -> tuple[FactorInputRecord, ...]:
    """Select the latest revision for each economic data point, only as known at cutoff."""
    candidates = [row for row in inputs if row.observed_at <= cutoff and row.available_at <= cutoff]
    latest: dict[tuple[str, str, datetime], FactorInputRecord] = {}
    for row in sorted(
        candidates,
        key=lambda item: (
            item.ticker,
            item.field,
            _utc(item.observed_at),
            _utc(item.available_at),
            item.revision,
            item.source_id,
        ),
    ):
        key = (row.ticker, row.field, _utc(row.observed_at))
        current = latest.get(key)
        if (
            current is not None
            and row.available_at == current.available_at
            and row.revision == current.revision
            and row != current
        ):
            raise ValueError(f"ambiguous point-in-time factor revision for {key}")
        latest[key] = row
    return tuple(
        sorted(
            latest.values(),
            key=lambda item: (item.ticker, item.field, _utc(item.observed_at)),
        )
    )


def _latest_field(
    rows: tuple[FactorInputRecord, ...], ticker: str, field: str, window_start: datetime
) -> FactorInputRecord | None:
    matches = [
        row
        for row in rows
        if row.ticker == ticker and row.field == field and row.observed_at >= window_start
    ]
    return max(
        matches,
        key=lambda row: (_utc(row.observed_at), _utc(row.available_at), row.revision),
        default=None,
    )


def _quality(
    rows: tuple[FactorInputRecord, ...], ticker: str, window_start: datetime
) -> tuple[float, tuple[FactorInputRecord, ...]] | None:
    selected = tuple(
        _latest_field(rows, ticker, field, window_start)
        for field in ("return_on_equity", "gross_profitability", "debt_to_assets")
    )
    if any(row is None for row in selected):
        return None
    complete = tuple(row for row in selected if row is not None)
    value = (complete[0].value + complete[1].value - complete[2].value) / 3.0
    return value, complete


def _momentum(
    rows: tuple[FactorInputRecord, ...], ticker: str, window_start: datetime
) -> tuple[float, tuple[FactorInputRecord, ...]] | None:
    prices = [
        row
        for row in rows
        if row.ticker == ticker and row.field == "price" and row.observed_at >= window_start
    ]
    if len(prices) < 2:
        return None
    prices.sort(key=lambda row: (_utc(row.observed_at), _utc(row.available_at), row.revision))
    start, end = prices[0], prices[-1]
    if start.value <= 0.0:
        return None
    return end.value / start.value - 1.0, (start, end)


def _low_volatility(
    rows: tuple[FactorInputRecord, ...], ticker: str, window_start: datetime
) -> tuple[float, tuple[FactorInputRecord, ...]] | None:
    returns = tuple(
        sorted(
            (
                row
                for row in rows
                if row.ticker == ticker
                and row.field == "return"
                and row.observed_at >= window_start
            ),
            key=lambda row: (_utc(row.observed_at), _utc(row.available_at), row.revision),
        )
    )
    if len(returns) < 2:
        return None
    mean = sum(row.value for row in returns) / len(returns)
    variance = sum((row.value - mean) ** 2 for row in returns) / len(returns)
    return -math.sqrt(variance), returns


def calculate_factor_value(
    definition: FactorDefinition,
    *,
    ticker: str,
    inputs: tuple[FactorInputRecord, ...],
    as_of: datetime,
) -> tuple[float, datetime, tuple[str, ...]] | None:
    """Calculate one representative factor value with lagged PIT revision selection.

    Quality is ``(ROE + gross profitability - debt/assets) / 3``; momentum is the
    lagged-window price return; volatility is negative population volatility (so higher
    is better).  Unsupported families and incomplete inputs abstain by returning ``None``.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    symbol = normalize_ticker(ticker)
    cutoff = as_of - timedelta(days=definition.lag_days)
    window_start = cutoff - timedelta(days=definition.lookback_days)
    visible = _visible_revisions(inputs, cutoff=cutoff)
    calculated: tuple[float, tuple[FactorInputRecord, ...]] | None
    if definition.family in {"quality", "profitability"}:
        calculated = _quality(visible, symbol, window_start)
    elif definition.family == "momentum":
        calculated = _momentum(visible, symbol, window_start)
    elif definition.family == "volatility":
        calculated = _low_volatility(visible, symbol, window_start)
    else:
        return None
    if calculated is None:
        return None
    value, used = calculated
    if not math.isfinite(value):
        return None
    available_at = max(row.available_at for row in used)
    source_ids = tuple(sorted({row.source_id for row in used if row.source_id}))
    return value, available_at, source_ids


def evaluate_factor(
    definition: FactorDefinition,
    *,
    snapshot: UniverseSnapshot,
    inputs: tuple[FactorInputRecord, ...],
    calculation_id: str,
    fail_on_missing: bool = False,
) -> FactorRun:
    """Evaluate eligible members, explicitly abstaining when inputs are unavailable."""
    observations: list[FactorObservation] = []
    abstentions: list[FactorAbstention] = []
    eligible = {decision.member_id for decision in snapshot.decisions if decision.eligible}
    for member in snapshot.members:
        if member.member_id not in eligible:
            continue
        result = calculate_factor_value(
            definition,
            ticker=member.ticker,
            inputs=inputs,
            as_of=snapshot.as_of,
        )
        if result is None:
            abstentions.append(
                FactorAbstention(member.ticker, "unavailable_or_unsupported_point_in_time_inputs")
            )
            continue
        value, input_available_at, source_ids = result
        slug = re.sub(r"[^a-z0-9]+", "-", member.ticker.lower()).strip("-")
        observations.append(
            build_hashed(
                FactorObservation,
                observation_id=f"observation-{slug}-{definition.factor_id}",
                factor_id=definition.factor_id,
                universe_snapshot_id=snapshot.snapshot_id,
                ticker=member.ticker,
                value=value,
                input_available_at=input_available_at,
                source_ids=source_ids,
                calculation_id=calculation_id,
                as_of=snapshot.as_of,
                available_at=snapshot.as_of,
            )
        )
    run = FactorRun(tuple(observations), tuple(abstentions))
    if fail_on_missing and run.abstentions:
        names = ", ".join(item.ticker for item in run.abstentions)
        raise FactorInputUnavailable(f"factor evaluation abstained for: {names}")
    return run
