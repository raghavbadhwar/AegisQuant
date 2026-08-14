"""Fixture-only, jurisdiction-neutral venue conformance contracts with no transport."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc
from aegisquant.contracts.release import ProductionReleaseManifest
from aegisquant.contracts.risk import OrderBundle, OrderType

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _parse_utc(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("venue timestamps must be UTC datetimes")
    return require_utc(value)


def _exact_dns_hostname(value: str) -> str:
    if (
        value != value.lower()
        or len(value) > 253
        or any(token in value for token in ("://", ":", "*"))
    ):
        raise ValueError("venue hostname must be an exact lowercase DNS name")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("venue hostname must not be an IP address")
    if "." not in value or any(not _DNS_LABEL.fullmatch(label) for label in value.split(".")):
        raise ValueError("venue hostname must be an exact lowercase DNS name")
    return value


class VenueAdapterProfile(StrictModel):
    """Safety capabilities a future provider adapter must prove with recorded fixtures."""

    schema_version: Literal[1] = 1
    adapter_id: Identifier
    broker_id: Identifier
    compliance_policy_pack_id: Identifier
    compliance_policy_pack_digest: Sha256Digest
    allowed_hostnames: tuple[str, ...]
    supported_order_types: tuple[OrderType, ...]
    supports_client_order_idempotency: Literal[True] = True
    supports_order_status_retrieval: Literal[True] = True
    supports_cancellation: Literal[True] = True
    max_submission_timeout_seconds: int = Field(ge=1, le=60)
    reviewed_at: datetime
    expires_at: datetime

    @field_validator("allowed_hostnames", "supported_order_types", mode="before")
    @classmethod
    def arrays(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("allowed_hostnames")
    @classmethod
    def exact_hostnames(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_exact_dns_hostname(hostname) for hostname in value)
        if not checked or len(checked) > 8 or checked != tuple(sorted(set(checked))):
            raise ValueError("venue hostnames must be 1-8 unique sorted exact DNS names")
        return checked

    @field_validator("supported_order_types")
    @classmethod
    def exact_order_types(cls, value: tuple[OrderType, ...]) -> tuple[OrderType, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("venue profile requires unique supported order types")
        return value

    @field_validator("reviewed_at", "expires_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def validity_window(self) -> VenueAdapterProfile:
        if self.expires_at <= self.reviewed_at:
            raise ValueError("venue profile validity window is invalid")
        return self


class VenueSubmissionCommand(StrictModel):
    """Exact fixture command for conformance tests; it is never a network request."""

    schema_version: Literal[1] = 1
    tenant_id: Identifier
    release_manifest_digest: Sha256Digest
    compliance_policy_pack_id: Identifier
    compliance_policy_pack_digest: Sha256Digest
    legal_entity_id: Identifier
    account_id: Identifier
    broker_id: Identifier
    request_id: UUID
    order_bundle_digest: Sha256Digest
    client_order_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=1000)
    submission_hostname: str
    not_before: datetime
    expires_at: datetime

    @field_validator("client_order_ids", mode="before")
    @classmethod
    def order_id_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("submission_hostname")
    @classmethod
    def exact_hostname(cls, value: str) -> str:
        return _exact_dns_hostname(value)

    @field_validator("not_before", "expires_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def scope(self) -> VenueSubmissionCommand:
        if self.expires_at <= self.not_before:
            raise ValueError("venue command validity window is invalid")
        if len(self.client_order_ids) != len(set(self.client_order_ids)):
            raise ValueError("venue command order IDs must be unique")
        return self


class VenueOrderAcknowledgement(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    account_id: Identifier
    broker_id: Identifier
    command_digest: Sha256Digest
    client_order_id: Identifier
    venue_order_id: Identifier
    status: Literal["ACCEPTED", "REJECTED"]
    observed_at: datetime

    @field_validator("observed_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)


class VenueConformanceReport(StrictModel):
    schema_version: Literal[1] = 1
    outcome: Literal["CONFORMANT"] = "CONFORMANT"
    tenant_id: Identifier
    broker_id: Identifier
    command_digest: Sha256Digest
    acknowledged_order_ids: tuple[Identifier, ...]
    report_digest: Sha256Digest
    verified_at: datetime

    @field_validator("acknowledged_order_ids", mode="before")
    @classmethod
    def order_id_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("verified_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)


class VenueConformanceInput(StrictModel):
    schema_version: Literal[1] = 1
    release: ProductionReleaseManifest
    profile: VenueAdapterProfile
    order_bundle: OrderBundle
    command: VenueSubmissionCommand
    acknowledgements: tuple[VenueOrderAcknowledgement, ...]
    now: datetime

    @field_validator("acknowledgements", mode="before")
    @classmethod
    def acknowledgement_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("now", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)
