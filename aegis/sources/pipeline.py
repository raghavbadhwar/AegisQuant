"""Raw-first, typed source acquisition gateway."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from aegis.contracts import (
    EvidenceBundle,
    EvidenceRecord,
    FetchedDocument,
    SourceAcquisitionResult,
    SourceManifest,
    SourceRequest,
    canonical_sha256,
)

from .normalizer import normalize
from .planner import SourcePlanner, SourcePlanningError
from .raw_store import RawStore
from .registry import SourceRegistry


class SourcePolicyDenied(RuntimeError):
    pass


class SourceConnector(Protocol):
    def fetch(
        self, request: SourceRequest, manifest: SourceManifest, request_id: str
    ) -> FetchedDocument: ...


class SourceGateway:
    """Only component allowed to turn connector bytes into registered evidence."""

    def __init__(
        self,
        registry: SourceRegistry,
        planner: SourcePlanner,
        raw_store: RawStore,
        connectors: dict[str, SourceConnector],
    ) -> None:
        self.registry = registry
        self.planner = planner
        self.raw_store = raw_store
        self.connectors = connectors

    def acquire(self, request: SourceRequest) -> tuple[SourceAcquisitionResult, EvidenceBundle]:
        if request.mode != "live_research":
            raise SourcePolicyDenied(f"source acquisition is forbidden in {request.mode} mode")
        try:
            plan = self.planner.plan(request)
        except SourcePlanningError as exc:
            raise SourcePolicyDenied(str(exc)) from exc
        if plan.estimated_cost_usd > request.max_cost_usd:
            raise SourcePolicyDenied("source plan exceeds the request cost ceiling")
        receipts = []
        documents = []
        evidence: list[EvidenceRecord] = []
        for source_id, method in zip(plan.source_ids, plan.acquisition_methods, strict=True):
            manifest = self.registry.get(source_id)
            try:
                connector = self.connectors[method]
            except KeyError as exc:
                raise SourcePolicyDenied(f"connector unavailable: {method}") from exc
            fetched = connector.fetch(request, manifest, plan.request_id)
            if fetched.source_id != source_id or fetched.request_id != plan.request_id:
                raise SourcePolicyDenied("connector response identity mismatch")
            host = (urlparse(fetched.url).hostname or "").lower()
            if not any(
                host == domain.lower() or host.endswith(f".{domain.lower()}")
                for domain in manifest.domains
            ):
                raise SourcePolicyDenied("connector response URL is outside source domains")
            receipt = self.raw_store.commit(fetched)
            document = normalize(
                receipt,
                manifest,
                available_at=fetched.fetched_at,
                entity_ids=request.entity_ids,
                document_type=request.information_type,
            )
            evidence_id = f"web-{document.normalized_content_hash[:24]}"
            record = EvidenceRecord(
                evidence_id=evidence_id,
                source_id=source_id,
                source_url=fetched.url,
                content_hash=receipt.content_hash,
                raw_uri=receipt.raw_uri,
                entity_ids=document.entity_ids,
                document_type=document.document_type,
                section="normalized-document",
                coordinates=f"document_id={document.document_id}",
                available_at=document.source_time.available_at,
                retrieved_at=document.source_time.retrieved_at,
                source_quality=manifest.reliability_prior,
                extraction_confidence=document.extraction_confidence,
                historical_safe=manifest.historical_safe,
                injection_flags=document.injection_flags,
                parser_version=document.parser_version,
                extractor_version="source-gateway-v1",
                source_manifest_version=manifest.version,
                normalized_content_hash=document.normalized_content_hash,
            )
            receipts.append(receipt)
            documents.append(document)
            evidence.append(record)
        bundle = EvidenceBundle(
            case_id=request.case_id,
            as_of=max(record.available_at for record in evidence),
            records=evidence,
            mode="live_research",
        )
        result_payload = {
            "plan": plan,
            "raw_receipts": receipts,
            "documents": documents,
            "evidence_ids": sorted(record.evidence_id for record in evidence),
        }
        result = SourceAcquisitionResult(
            plan=plan,
            raw_receipts=receipts,
            documents=documents,
            evidence_ids=sorted(record.evidence_id for record in evidence),
            result_hash=canonical_sha256(result_payload),
        )
        return result, bundle
