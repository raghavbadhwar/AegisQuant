"""Batch forecast provider seam shared by replay and the later LangGraph desk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from aegis.contracts import AlphaForecast, EvidenceBundle, EvidenceRecord, ResearchCase
from aegis.data import MarketSnapshot


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


@runtime_checkable
class ForecastProvider(Protocol):
    network_enabled: bool

    def evidence_bundle(self, case: ResearchCase) -> EvidenceBundle: ...

    def forecast_batch(
        self, case: ResearchCase, snapshot: MarketSnapshot
    ) -> tuple[AlphaForecast, ...]: ...


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

    def evidence_bundle(self, case: ResearchCase) -> EvidenceBundle:
        return EvidenceBundle(
            case_id=case.case_id, as_of=case.created_at, records=list(self._evidence)
        )

    def forecast_batch(
        self, case: ResearchCase, snapshot: MarketSnapshot
    ) -> tuple[AlphaForecast, ...]:
        if case.mode != "replay":
            raise ForecastIntegrityError("fixture provider is replay-only")
        available_tickers = {bar.ticker for bar in snapshot.bars}
        requested = set(case.tickers)
        if not requested.issubset(available_tickers):
            missing = sorted(requested.difference(available_tickers))
            raise ForecastIntegrityError(f"snapshot missing requested tickers: {missing}")
        selected = tuple(forecast for forecast in self._forecasts if forecast.ticker in requested)
        if {forecast.ticker for forecast in selected} != requested:
            raise ForecastIntegrityError("replay forecasts do not cover the requested universe")
        evidence_ids = {record.evidence_id for record in self._evidence}
        for forecast in selected:
            if forecast.as_of != case.as_of or forecast.horizon_days != case.horizon_days:
                raise ForecastIntegrityError("forecast date/horizon does not match case")
            if not set(forecast.evidence_ids).issubset(evidence_ids):
                raise ForecastIntegrityError(
                    f"unknown evidence ID in forecast for {forecast.ticker}"
                )
        self.evidence_bundle(case)
        return selected


def load_replay_manifest(path: str | Path) -> ReplayManifest:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return ReplayManifest.model_validate(payload)
    except Exception as exc:
        raise ForecastIntegrityError(f"invalid replay case manifest: {path}") from exc
