#!/usr/bin/env python3
"""Export or verify the versioned JSON Schema contract fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from aegisquant.contracts.artifact import ArtifactEnvelope, ValidationReceipt
from aegisquant.contracts.capability import CapabilityGrant, ToolAuthorizationRequest
from aegisquant.contracts.case import InvestmentCase, InvestmentCaseRequest
from aegisquant.contracts.evidence import EvidenceRecord, NumericClaim, RightsManifest
from aegisquant.contracts.risk import (
    HumanApprovalPayload,
    OrderBundle,
    RiskDecisionPayload,
    SignedRiskDecision,
)

SCHEMAS: dict[str, Any] = {
    "artifact-envelope-v1": ArtifactEnvelope,
    "capability-grant-v1": CapabilityGrant,
    "evidence-record-v1": EvidenceRecord,
    "human-approval-payload-v1": HumanApprovalPayload,
    "investment-case-request-v1": InvestmentCaseRequest,
    "investment-case-v1": InvestmentCase,
    "numeric-claim-v1": NumericClaim,
    "order-bundle-v1": OrderBundle,
    "rights-manifest-v1": RightsManifest,
    "risk-decision-payload-v1": RiskDecisionPayload,
    "signed-risk-decision-v1": SignedRiskDecision,
    "tool-authorization-request-v1": ToolAuthorizationRequest,
    "validation-receipt-v1": ValidationReceipt,
}
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "schemas"


def rendered_schema(model: Any) -> bytes:
    return (
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for name, model in SCHEMAS.items():
        path = OUTPUT / f"{name}.json"
        expected = rendered_schema(model)
        if arguments.check:
            if not path.exists() or path.read_bytes() != expected:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_bytes(expected)
    if stale:
        print("stale contract schemas:")
        print("\n".join(f"- {item}" for item in stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
