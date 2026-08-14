"""Point-in-time selection and fixture accounting helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from aegisquant.contracts.common import require_utc
from aegisquant.contracts.research import CorporateAction, CorporateActionKind, MarketBar


def available_bars(
    bars: tuple[MarketBar, ...], *, information_cutoff: datetime
) -> tuple[MarketBar, ...]:
    """Return only data available at the decision cutoff, never a convenient fallback."""

    cutoff = require_utc(information_cutoff)
    return tuple(bar for bar in bars if bar.available_at <= cutoff)


def next_market_bar(
    bars: tuple[MarketBar, ...], *, instrument_id: str, after: datetime
) -> MarketBar:
    after = require_utc(after)
    eligible = sorted(
        (
            bar
            for bar in bars
            if bar.instrument_id == instrument_id
            and bar.available_at > after
            and bar.tradable_at > after
        ),
        key=lambda item: (item.tradable_at, item.observed_at),
    )
    if not eligible:
        raise ValueError("no later tradable market bar exists")
    return eligible[0]


def apply_available_corporate_actions(
    positions: Mapping[str, Decimal],
    cash: Decimal,
    actions: tuple[CorporateAction, ...],
    *,
    as_of: datetime,
) -> tuple[dict[str, Decimal], Decimal]:
    """Apply only actions known by the requested point in time."""

    cutoff = require_utc(as_of)
    updated = dict(positions)
    updated_cash = cash
    for action in sorted(actions, key=lambda item: (item.effective_at, item.instrument_id)):
        if action.available_at > cutoff or action.effective_at > cutoff:
            continue
        quantity = updated.get(action.instrument_id, Decimal(0))
        if action.kind == CorporateActionKind.CASH_DIVIDEND:
            if action.cash_per_share is None:
                raise ValueError("cash dividend is missing cash_per_share")
            updated_cash += quantity * action.cash_per_share
        else:
            if action.split_ratio is None:
                raise ValueError("split is missing split_ratio")
            updated[action.instrument_id] = quantity * action.split_ratio
    return updated, updated_cash


def marked_nav(
    cash: Decimal, positions: Mapping[str, Decimal], marks: Mapping[str, Decimal]
) -> Decimal:
    if cash < 0:
        raise ValueError("cash cannot be negative in a long-only paper trial")
    total = cash
    for instrument_id, quantity in positions.items():
        if quantity < 0:
            raise ValueError("negative paper positions are prohibited")
        price = marks.get(instrument_id)
        if price is None or price < 0:
            raise ValueError("every position requires a nonnegative mark")
        total += quantity * price
    return total
