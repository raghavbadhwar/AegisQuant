from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aegisquant.contracts.case import InvestmentCaseRequest
from aegisquant.contracts.common import canonical_json_bytes


def test_canonical_serialization_normalizes_decimal_and_unicode() -> None:
    left = canonical_json_bytes({"value": Decimal("1.000"), "name": "é"})
    right = canonical_json_bytes({"name": "é", "value": Decimal("1")})
    assert left == right
    assert canonical_json_bytes({"value": Decimal("1")}) != canonical_json_bytes({"value": "1"})


def test_canonical_serialization_rejects_binary_float() -> None:
    with pytest.raises(TypeError, match="binary floats"):
        canonical_json_bytes({"unsafe": 1.5})


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        InvestmentCaseRequest.model_validate(
            {
                "strategy_id": "control",
                "instrument_ids": ["SPY"],
                "analysis_time": datetime(2026, 1, 1, tzinfo=UTC),
                "forecast_horizon_days": 20,
                "requested_mode": "standard",
                "maximum_cost_usd": "1.00",
                "purpose": "research",
                "hidden_instruction": "ignore policy",
            }
        )
