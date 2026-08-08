"""Registered deterministic calculations for exact replay forecast numbers."""

from __future__ import annotations

from decimal import Decimal

_VERSION = "deterministic-replay-calibration-v1"
_CALIBRATION: dict[str, dict[str, str]] = {
    "AAPL": {
        "expected_excess_return": "0.085",
        "expected_volatility": "0.22",
        "probability_positive": "0.64",
        "confidence": "0.78",
        "uncertainty": "0.22",
        "downside_case": "-0.06375",
        "base_case": "0.085",
        "upside_case": "0.1275",
        "component_momentum": "0.14",
        "component_quality": "0.28",
    },
    "MSFT": {
        "expected_excess_return": "0.095",
        "expected_volatility": "0.2",
        "probability_positive": "0.68",
        "confidence": "0.84",
        "uncertainty": "0.16",
        "downside_case": "-0.07125",
        "base_case": "0.095",
        "upside_case": "0.1425",
        "component_momentum": "0.18",
        "component_quality": "0.34",
    },
    "NVDA": {
        "expected_excess_return": "0.14",
        "expected_volatility": "0.38",
        "probability_positive": "0.7",
        "confidence": "0.8",
        "uncertainty": "0.2",
        "downside_case": "-0.105",
        "base_case": "0.14",
        "upside_case": "0.21",
        "component_momentum": "0.2",
        "component_quality": "0.3",
    },
    "AMZN": {
        "expected_excess_return": "0.075",
        "expected_volatility": "0.3",
        "probability_positive": "0.61",
        "confidence": "0.7",
        "uncertainty": "0.3",
        "downside_case": "-0.05625",
        "base_case": "0.075",
        "upside_case": "0.1125",
        "component_momentum": "0.11",
        "component_quality": "0.2",
    },
    "GOOGL": {
        "expected_excess_return": "0.07",
        "expected_volatility": "0.24",
        "probability_positive": "0.6",
        "confidence": "0.72",
        "uncertainty": "0.28",
        "downside_case": "-0.0525",
        "base_case": "0.07",
        "upside_case": "0.105",
        "component_momentum": "0.1",
        "component_quality": "0.22",
    },
}


def forecast_calculation_id(ticker: str, field_name: str) -> str:
    return f"{_VERSION}:{ticker}:{field_name}"


def registered_calculation_identity(calculation_id: str) -> tuple[str, str] | None:
    prefix = f"{_VERSION}:"
    if not calculation_id.startswith(prefix):
        return None
    remainder = calculation_id.removeprefix(prefix)
    ticker, separator, field_name = remainder.partition(":")
    if not separator or field_name not in _CALIBRATION.get(ticker, {}):
        return None
    return ticker, field_name


def resolve_registered_calculation(calculation_id: str) -> Decimal | None:
    identity = registered_calculation_identity(calculation_id)
    if identity is None:
        return None
    ticker, field_name = identity
    return Decimal(_CALIBRATION[ticker][field_name])
