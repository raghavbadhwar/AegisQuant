"""Research-provider seam shared by replay, historical, and LangGraph desks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from aegis.contracts import (
    AlphaForecast,
    ClaimGraphSnapshot,
    EvidenceAuditResult,
    EvidenceBundle,
    EvidenceRecord,
    MemoryHit,
    QuantResearchBundle,
    ResearchArtifact,
    ResearchCase,
    canonical_sha256,
)
from aegis.data import MarketSnapshot
from aegis.observability import GraphEvent


class ForecastIntegrityError(RuntimeError):
    """Replay or model output is missing, malformed, or inconsistent."""


class ReplayManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    mode: str
    as_of: AwareDatetime
    created_at: AwareDatetime
    horizon_days: int = Field(gt=0)
    research_question: str = Field(min_length=1)
    tickers: list[str] = Field(min_length=1)
    fund_path: str
    agent_output_fixture: str
    forecast_fixture: str
    evidence_fixture: str

    def research_case(self) -> ResearchCase:
        return ResearchCase(
            case_id=self.case_id,
            mode="replay",
            as_of=self.as_of,
            created_at=self.created_at,
            horizon_days=self.horizon_days,
            research_question=self.research_question,
            tickers=self.tickers,
        )


class ResearchDossier(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    as_of: AwareDatetime
    evidence: EvidenceBundle
    artifacts: tuple[ResearchArtifact, ...]
    forecasts: tuple[AlphaForecast, ...]
    graph_events: tuple[GraphEvent, ...]
    claim_graph: ClaimGraphSnapshot | None = None
    evidence_audit: EvidenceAuditResult | None = None
    memory_hits: tuple[MemoryHit, ...] = ()
    memory_snapshot_hash: str = canonical_sha256([])
    relation_snapshot_hash: str = canonical_sha256([])
    quant_research_bundle: QuantResearchBundle | None = None
    content_hash: str

    def hash_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "as_of": self.as_of,
            "evidence": self.evidence,
            "artifacts": self.artifacts,
            "forecasts": self.forecasts,
            "graph_events": self.graph_events,
            "claim_graph": self.claim_graph,
            "evidence_audit": self.evidence_audit,
            "memory_hits": self.memory_hits,
            "memory_snapshot_hash": self.memory_snapshot_hash,
            "relation_snapshot_hash": self.relation_snapshot_hash,
            **(
                {"quant_research_bundle": self.quant_research_bundle}
                if self.quant_research_bundle is not None
                else {}
            ),
        }

    @model_validator(mode="after")
    def dossier_is_closed_and_hashed(self) -> ResearchDossier:
        if self.evidence.case_id != self.case_id or self.evidence.as_of != self.as_of:
            raise ValueError("dossier evidence does not match the case")
        evidence_ids = {record.evidence_id for record in self.evidence.records}
        for forecast in self.forecasts:
            if not forecast.abstained and not set(forecast.evidence_ids).issubset(evidence_ids):
                raise ValueError("forecast cites evidence outside the dossier")
        for artifact in self.artifacts:
            if not set(artifact.evidence_ids).issubset(evidence_ids):
                raise ValueError("artifact cites evidence outside the dossier")
        if self.claim_graph is not None:
            if self.claim_graph.case_id != self.case_id:
                raise ValueError("claim graph does not match the dossier case")
            claim_ids = {claim.claim_id for claim in self.claim_graph.claims}
            if any(not set(artifact.claim_ids).issubset(claim_ids) for artifact in self.artifacts):
                raise ValueError("artifact cites a claim outside the dossier claim graph")
        if self.evidence_audit is not None and (
            self.evidence_audit.case_id != self.case_id or not self.evidence_audit.approved
        ):
            raise ValueError("dossier requires an approved deterministic evidence audit")
        if self.content_hash != canonical_sha256(self.hash_payload()):
            raise ValueError("dossier content_hash mismatch")
        return self


def build_dossier(
    case: ResearchCase,
    evidence: EvidenceBundle,
    artifacts: tuple[ResearchArtifact, ...],
    forecasts: tuple[AlphaForecast, ...],
    graph_events: tuple[GraphEvent, ...],
    claim_graph: ClaimGraphSnapshot | None = None,
    evidence_audit: EvidenceAuditResult | None = None,
    memory_hits: tuple[MemoryHit, ...] = (),
    memory_snapshot_hash: str = canonical_sha256([]),
    relation_snapshot_hash: str = canonical_sha256([]),
    quant_research_bundle: QuantResearchBundle | None = None,
) -> ResearchDossier:
    payload = {
        "case_id": case.case_id,
        "as_of": case.as_of,
        "evidence": evidence,
        "artifacts": artifacts,
        "forecasts": forecasts,
        "graph_events": graph_events,
        "claim_graph": claim_graph,
        "evidence_audit": evidence_audit,
        "memory_hits": memory_hits,
        "memory_snapshot_hash": memory_snapshot_hash,
        "relation_snapshot_hash": relation_snapshot_hash,
        **(
            {"quant_research_bundle": quant_research_bundle}
            if quant_research_bundle is not None
            else {}
        ),
    }
    return ResearchDossier(
        case_id=case.case_id,
        as_of=case.as_of,
        evidence=evidence,
        artifacts=artifacts,
        forecasts=forecasts,
        graph_events=graph_events,
        claim_graph=claim_graph,
        evidence_audit=evidence_audit,
        memory_hits=memory_hits,
        memory_snapshot_hash=memory_snapshot_hash,
        relation_snapshot_hash=relation_snapshot_hash,
        quant_research_bundle=quant_research_bundle,
        content_hash=canonical_sha256(payload),
    )


@runtime_checkable
class ForecastProvider(Protocol):
    network_enabled: bool

    def research(self, case: ResearchCase, snapshot: MarketSnapshot) -> ResearchDossier: ...


class FixtureForecastProvider:
    """Fail-closed provider for deterministic local replay artifacts."""

    network_enabled = False

    def __init__(self, forecast_path: str | Path, evidence_path: str | Path) -> None:
        self.forecast_path = Path(forecast_path).resolve()
        self.evidence_path = Path(evidence_path).resolve()
        self._forecasts = self._load_forecasts()
        self._evidence = self._load_evidence()

    def _load_forecasts(self) -> tuple[AlphaForecast, ...]:
        if not self.forecast_path.is_file():
            raise ForecastIntegrityError(f"missing replay forecasts: {self.forecast_path}")
        try:
            forecasts = TypeAdapter(list[AlphaForecast]).validate_json(
                self.forecast_path.read_bytes()
            )
        except Exception as exc:
            raise ForecastIntegrityError("invalid replay forecast fixture") from exc
        tickers = [forecast.ticker for forecast in forecasts]
        if len(tickers) != len(set(tickers)):
            raise ForecastIntegrityError("duplicate ticker forecasts in replay fixture")
        return tuple(sorted(forecasts, key=lambda forecast: forecast.ticker))

    def _load_evidence(self) -> tuple[EvidenceRecord, ...]:
        if not self.evidence_path.is_file():
            raise ForecastIntegrityError(f"missing replay evidence: {self.evidence_path}")
        records: list[EvidenceRecord] = []
        try:
            for line in self.evidence_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(EvidenceRecord.model_validate_json(line))
        except Exception as exc:
            raise ForecastIntegrityError("invalid replay evidence fixture") from exc
        ids = [record.evidence_id for record in records]
        if len(ids) != len(set(ids)):
            raise ForecastIntegrityError("duplicate evidence IDs in replay fixture")
        return tuple(sorted(records, key=lambda record: record.evidence_id))

    def research(self, case: ResearchCase, snapshot: MarketSnapshot) -> ResearchDossier:
        if case.mode != "replay":
            raise ForecastIntegrityError("fixture provider is replay-only")
        requested = set(case.tickers)
        available_tickers = {bar.ticker for bar in snapshot.bars}
        if not requested.issubset(available_tickers):
            missing = sorted(requested.difference(available_tickers))
            raise ForecastIntegrityError(f"snapshot missing requested tickers: {missing}")
        forecasts = tuple(forecast for forecast in self._forecasts if forecast.ticker in requested)
        if {forecast.ticker for forecast in forecasts} != requested:
            raise ForecastIntegrityError("replay forecasts do not cover the requested universe")
        evidence = EvidenceBundle(
            case_id=case.case_id,
            as_of=case.as_of,
            records=list(self._evidence),
            mode=case.mode,
        )
        evidence_ids = {record.evidence_id for record in self._evidence}
        for forecast in forecasts:
            if forecast.as_of != case.as_of or forecast.horizon_days != case.horizon_days:
                raise ForecastIntegrityError("forecast date/horizon does not match case")
            if not set(forecast.evidence_ids).issubset(evidence_ids):
                raise ForecastIntegrityError(
                    f"unknown evidence ID in forecast for {forecast.ticker}"
                )
        payload = {"forecasts": [item.model_dump(mode="json") for item in forecasts]}
        artifact = ResearchArtifact(
            artifact_id=f"{case.case_id}:replay-cio",
            case_id=case.case_id,
            artifact_type="replay_forecast_batch",
            producer_agent="replay-cio",
            model_alias="research-standard",
            actual_model="fixture/replay-cio-v2",
            skill_versions=["cio-synthesis@fixture-v2"],
            evidence_ids=sorted(evidence_ids),
            payload=payload,
            content_hash=canonical_sha256(payload),
        )
        event = GraphEvent(
            event_id=f"{case.case_id}:fixture-loaded",
            case_id=case.case_id,
            sequence=0,
            node="replay-provider",
            event_type="provider_complete",
            status="completed",
            occurred_at=case.as_of,
            metadata={"forecast_count": len(forecasts)},
        )
        return build_dossier(case, evidence, (artifact,), forecasts, (event,))


class MultiStrategyFixtureProvider(FixtureForecastProvider):
    """Sealed replay provider allowing one forecast per declared model and ticker."""

    def __init__(
        self, forecast_path: str | Path, evidence_path: str | Path, quant_bundle_path: str | Path
    ) -> None:
        self.quant_bundle_path = Path(quant_bundle_path).resolve()
        super().__init__(forecast_path, evidence_path)
        try:
            self._quant_bundle = QuantResearchBundle.model_validate_json(
                self.quant_bundle_path.read_bytes()
            )
        except Exception as exc:
            raise ForecastIntegrityError("invalid sealed quant research bundle") from exc

    def _load_forecasts(self) -> tuple[AlphaForecast, ...]:
        if not self.forecast_path.is_file():
            raise ForecastIntegrityError(f"missing replay forecasts: {self.forecast_path}")
        try:
            forecasts = TypeAdapter(list[AlphaForecast]).validate_json(
                self.forecast_path.read_bytes()
            )
        except Exception as exc:
            raise ForecastIntegrityError("invalid multi-strategy forecast fixture") from exc
        identities = [(forecast.model_name, forecast.ticker) for forecast in forecasts]
        if len(identities) != len(set(identities)):
            raise ForecastIntegrityError("duplicate model/ticker forecasts in strategy fixture")
        if any(
            not isinstance(forecast.metadata.get("calibration_score"), (int, float))
            or not isinstance(forecast.metadata.get("regime_score"), (int, float))
            or not isinstance(forecast.metadata.get("evidence_quality"), (int, float))
            for forecast in forecasts
        ):
            raise ForecastIntegrityError("strategy forecasts require typed numeric batch metadata")
        return tuple(sorted(forecasts, key=lambda forecast: (forecast.model_name, forecast.ticker)))

    def research(self, case: ResearchCase, snapshot: MarketSnapshot) -> ResearchDossier:
        if self._quant_bundle.as_of != case.as_of:
            raise ForecastIntegrityError("quant research bundle cutoff does not match replay case")
        eligible = {
            decision.ticker
            for decision in self._quant_bundle.universe_snapshot.decisions
            if decision.eligible
        }
        if not set(case.tickers).issubset(eligible):
            raise ForecastIntegrityError("quant research bundle does not cover replay universe")
        base = super().research(case, snapshot)
        if any(
            not forecast.abstained
            and forecast.metadata.get("quant_bundle_hash") != self._quant_bundle.content_hash
            for forecast in base.forecasts
        ):
            raise ForecastIntegrityError(
                "non-abstained forecasts must bind the sealed quant bundle"
            )
        return build_dossier(
            case,
            base.evidence,
            base.artifacts,
            base.forecasts,
            base.graph_events,
            base.claim_graph,
            base.evidence_audit,
            base.memory_hits,
            base.memory_snapshot_hash,
            base.relation_snapshot_hash,
            self._quant_bundle,
        )


class HistoricalMultiStrategyFixtureProvider:
    """Exact-cutoff router for sealed, local institutional replay artifacts.

    Each historical cutoff has an independently validated forecast, evidence,
    and quant-bundle triplet. Missing cutoffs fail closed; this class neither
    extrapolates nor synthesizes research data.
    """

    network_enabled = False

    def __init__(
        self,
        artifacts: Mapping[str, tuple[str | Path, str | Path, str | Path]],
    ) -> None:
        if not artifacts:
            raise ForecastIntegrityError("historical provider requires sealed artifacts")
        self._providers: dict[str, MultiStrategyFixtureProvider] = {}
        for cutoff, paths in artifacts.items():
            if len(paths) != 3:
                raise ForecastIntegrityError("historical artifact triplet is incomplete")
            try:
                # Validate an ISO-aware key without normalizing away precision.
                from datetime import datetime

                instant = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise ValueError("naive cutoff")
            except (TypeError, ValueError) as exc:
                raise ForecastIntegrityError(
                    "historical artifact cutoff must be ISO-aware"
                ) from exc
            self._providers[cutoff] = MultiStrategyFixtureProvider(*paths)

    def research(self, case: ResearchCase, snapshot: MarketSnapshot) -> ResearchDossier:
        cutoff = case.as_of.isoformat()
        provider = self._providers.get(cutoff)
        if provider is None:
            raise ForecastIntegrityError(
                "missing sealed historical institutional artifacts for exact case cutoff"
            )
        # The immutable artifact loader is deliberately replay-only, so use a
        # mode-only clone for file parsing and reconstruct the dossier against
        # the original historical case.  No market, evidence, or forecast data
        # is synthesized or altered by this adaptation.
        replay_case = case.model_copy(update={"mode": "replay"})
        base = provider.research(replay_case, snapshot)
        return build_dossier(
            case,
            base.evidence,
            base.artifacts,
            base.forecasts,
            base.graph_events,
            base.claim_graph,
            base.evidence_audit,
            base.memory_hits,
            base.memory_snapshot_hash,
            base.relation_snapshot_hash,
            provider._quant_bundle,
        )


def load_replay_manifest(path: str | Path) -> ReplayManifest:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return ReplayManifest.model_validate(payload)
    except Exception as exc:
        raise ForecastIntegrityError(f"invalid replay case manifest: {path}") from exc
