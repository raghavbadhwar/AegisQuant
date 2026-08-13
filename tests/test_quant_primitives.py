from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aegisquant.quant.portfolio import Forecast, PortfolioPolicy, blend_forecasts, propose_long_only
from aegisquant.quant.timeline import ExecutionTimeline, TradableBar, next_tradable_bar


def forecast(**changes: object) -> Forecast:
    values: dict[str, object] = {
        "instrument_id": "AAA",
        "horizon_days": 20,
        "expected_return": "0.10",
        "probability_positive": "0.60",
        "confidence": "0.80",
        "uncertainty": "0.20",
        "feature_provenance": ("price-v1",),
    }
    values.update(changes)
    return Forecast(**values)


def test_bearish_or_lower_confidence_forecast_never_increases_long_exposure() -> None:
    policy = PortfolioPolicy(maximum_position_weight="1", uncertainty_floor="0.01")
    positive = blend_forecasts((forecast(),), uncertainty_floor=policy.uncertainty_floor)
    bearish = blend_forecasts(
        (forecast(expected_return="-0.10"),), uncertainty_floor=policy.uncertainty_floor
    )
    lower_confidence = blend_forecasts(
        (forecast(confidence="0.40"),), uncertainty_floor=policy.uncertainty_floor
    )
    competing = blend_forecasts(
        (forecast(instrument_id="BBB"),), uncertainty_floor=policy.uncertainty_floor
    )
    assert propose_long_only((bearish,), policy=policy) == {}
    assert (
        propose_long_only((lower_confidence, competing), policy=policy)["AAA"]
        < propose_long_only((positive, competing), policy=policy)["AAA"]
    )


def test_horizon_mismatch_and_missing_provenance_are_conservative() -> None:
    with pytest.raises(ValueError, match="same-horizon"):
        blend_forecasts((forecast(), forecast(horizon_days=21)), uncertainty_floor=Decimal("0.01"))
    blended = blend_forecasts(
        (forecast(), forecast(expected_return="-0.10", feature_provenance=None)),
        uncertainty_floor=Decimal("0.01"),
    )
    assert blended.feature_provenance is None
    assert blended.uncertainty > Decimal("0.20")


def test_timeline_rejects_same_close_and_selects_next_tradable_bar() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="information_cutoff"):
        ExecutionTimeline(
            information_cutoff=now,
            decision_at=now,
            order_submitted_at=now,
            fill_at=now + timedelta(seconds=1),
        )
    first = TradableBar(instrument_id="AAA", observed_at=now, tradable_at=now + timedelta(days=1))
    second = TradableBar(instrument_id="AAA", observed_at=now, tradable_at=now + timedelta(days=2))
    assert next_tradable_bar((second, first), instrument_id="AAA", after=now) == first
