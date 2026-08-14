"""Long-only forecast blending and deterministic proposal construction."""

from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import FixedDecimal, Identifier, StrictModel

_HALF = Decimal("0.5")


class Forecast(StrictModel):
    instrument_id: Identifier
    horizon_days: int = Field(ge=1, le=3650)
    expected_return: FixedDecimal
    probability_positive: FixedDecimal
    confidence: FixedDecimal
    uncertainty: FixedDecimal
    feature_provenance: tuple[Identifier, ...] | None = None

    @field_validator("feature_provenance", mode="before")
    @classmethod
    def json_array_is_tuple(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("probability_positive", "confidence")
    @classmethod
    def unit_interval(cls, value: Decimal) -> Decimal:
        if not Decimal(0) <= value <= Decimal(1):
            raise ValueError("probability and confidence must be between zero and one")
        return value

    @field_validator("uncertainty")
    @classmethod
    def nonnegative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("uncertainty must be nonnegative")
        return value


class BlendedForecast(Forecast):
    model_count: int = Field(ge=1)


class PortfolioPolicy(StrictModel):
    maximum_position_weight: FixedDecimal = Decimal("0.20")
    uncertainty_floor: FixedDecimal = Decimal("0.01")

    @model_validator(mode="after")
    def sensible_limits(self) -> "PortfolioPolicy":
        if not Decimal(0) < self.maximum_position_weight <= Decimal(1):
            raise ValueError("maximum_position_weight must be in (0, 1]")
        if self.uncertainty_floor <= 0:
            raise ValueError("uncertainty_floor must be positive")
        return self


class TargetWeight(StrictModel):
    instrument_id: Identifier
    weight: FixedDecimal

    @field_validator("weight")
    @classmethod
    def nonnegative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("long-only target weights must be nonnegative")
        return value


class PortfolioTarget(StrictModel):
    """A fully accounted-for target: capped holdings plus explicit cash."""

    weights: tuple[TargetWeight, ...]
    cash_weight: FixedDecimal

    @field_validator("weights", mode="before")
    @classmethod
    def parse_weights(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def weights_are_complete(self) -> "PortfolioTarget":
        instruments = [item.instrument_id for item in self.weights]
        if len(set(instruments)) != len(instruments):
            raise ValueError("portfolio target contains duplicate instruments")
        if self.cash_weight < 0:
            raise ValueError("cash_weight must be nonnegative")
        if sum((item.weight for item in self.weights), Decimal(0)) + self.cash_weight != Decimal(1):
            raise ValueError("portfolio target weights and cash must sum to one")
        return self


def blend_forecasts(
    forecasts: tuple[Forecast, ...], *, uncertainty_floor: Decimal
) -> BlendedForecast:
    """Blend same-horizon forecasts without letting declared near-zero risk dominate."""

    if not forecasts:
        raise ValueError("at least one forecast is required")
    first = forecasts[0]
    if any(
        item.instrument_id != first.instrument_id or item.horizon_days != first.horizon_days
        for item in forecasts[1:]
    ):
        raise ValueError("only same-instrument, same-horizon forecasts can blend")
    if uncertainty_floor <= 0:
        raise ValueError("uncertainty_floor must be positive")
    weights = tuple(Decimal(1) / max(item.uncertainty, uncertainty_floor) for item in forecasts)
    denominator = sum(weights)
    expected_return = (
        sum(
            (
                item.expected_return * weight
                for item, weight in zip(forecasts, weights, strict=True)
            ),
            Decimal(0),
        )
        / denominator
    )
    probability = (
        sum(
            (
                item.probability_positive * weight
                for item, weight in zip(forecasts, weights, strict=True)
            ),
            Decimal(0),
        )
        / denominator
    )
    confidence = (
        sum(
            (item.confidence * weight for item, weight in zip(forecasts, weights, strict=True)),
            Decimal(0),
        )
        / denominator
    )
    mean_squared_uncertainty = (
        sum(
            (
                item.uncertainty * item.uncertainty * weight
                for item, weight in zip(forecasts, weights, strict=True)
            ),
            Decimal(0),
        )
        / denominator
    )
    disagreement = (
        sum(
            (
                (item.expected_return - expected_return) ** 2 * weight
                for item, weight in zip(forecasts, weights, strict=True)
            ),
            Decimal(0),
        )
        / denominator
    )
    provenance = [item.feature_provenance for item in forecasts]
    shared_provenance = (
        None
        if any(item is None for item in provenance)
        else tuple(
            sorted(set.intersection(*(set(item) for item in provenance if item is not None)))
        )
    )
    return BlendedForecast(
        instrument_id=first.instrument_id,
        horizon_days=first.horizon_days,
        expected_return=expected_return,
        probability_positive=probability,
        confidence=confidence,
        uncertainty=max((mean_squared_uncertainty + disagreement).sqrt(), uncertainty_floor),
        feature_provenance=shared_provenance,
        model_count=len(forecasts),
    )


def propose_long_only(
    forecasts: tuple[BlendedForecast, ...], *, policy: PortfolioPolicy
) -> dict[str, Decimal]:
    """Return sorted deterministic long weights; bearish or abstaining inputs remain cash."""

    instrument_ids = [item.instrument_id for item in forecasts]
    if len(set(instrument_ids)) != len(instrument_ids):
        raise ValueError("only one blended forecast per instrument is allowed")
    scores = {
        item.instrument_id: max(item.expected_return, Decimal(0))
        * max(item.probability_positive - _HALF, Decimal(0))
        * item.confidence
        / max(item.uncertainty, policy.uncertainty_floor)
        for item in forecasts
    }
    total = sum(scores.values())
    if total == 0:
        return {}
    return {
        instrument_id: min(score / total, policy.maximum_position_weight)
        for instrument_id, score in sorted(scores.items())
        if score > 0
    }


def build_long_only_target(
    forecasts: tuple[BlendedForecast, ...], *, policy: PortfolioPolicy
) -> PortfolioTarget:
    """Preserve cap-induced residual exposure as cash instead of hiding it."""

    proposed = propose_long_only(forecasts, policy=policy)
    weights = tuple(
        TargetWeight(instrument_id=instrument_id, weight=weight)
        for instrument_id, weight in proposed.items()
    )
    invested = sum((item.weight for item in weights), Decimal(0))
    return PortfolioTarget(weights=weights, cash_weight=Decimal(1) - invested)
