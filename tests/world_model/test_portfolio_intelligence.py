from datetime import UTC, datetime

import pytest

from aegis.reporting.traceability import RunLedgerReceiptReference
from aegis.world_model.portfolio_intelligence import (
    CausalExposureReport,
    CausalPathExposure,
    PortfolioScenarioImpactReport,
    ScenarioImpactContribution,
    derive_causal_exposure_report,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _receipt(run_id: str) -> RunLedgerReceiptReference:
    return RunLedgerReceiptReference(
        ledger_id="v3-engineering-ledger",
        run_id=run_id,
        record_hash=("a" if run_id == "run-1" else "b") * 64,
        snapshot_hash="c" * 64,
        as_of=NOW,
    )


def _contribution(
    contribution_id: str, run_id: str, mechanism_id: str, path_id: str, net: float
) -> ScenarioImpactContribution:
    return ScenarioImpactContribution(
        contribution_id=contribution_id,
        v3_run_id=run_id,
        mechanism_id=mechanism_id,
        causal_path_id=path_id,
        gross_candidate_impact=net + 1.0,
        overlap_adjustment=-1.0,
        net_candidate_impact=net,
    ).sealed()


def _report() -> PortfolioScenarioImpactReport:
    contributions = (
        _contribution("impact-1", "run-1", "ai-capex", "capex-to-supplier", -3.0),
        _contribution("impact-2", "run-2", "ai-capex", "capex-to-supplier", -2.0),
        _contribution("impact-3", "run-2", "power-capacity", "power-to-supplier", 1.0),
    )
    return PortfolioScenarioImpactReport(
        report_id="portfolio-scenario-impact-v1",
        portfolio_id="v3-paper-portfolio-v1",
        as_of=NOW,
        scenario_run_id="candidate-scenario-run-v1",
        scenario_run_hash="d" * 64,
        v3_run_receipts=(_receipt("run-1"), _receipt("run-2")),
        contributions=contributions,
        declared_net_candidate_impact=-4.0,
    ).sealed()


def test_portfolio_scenario_impact_is_receipt_bound_and_exposure_is_reconciled() -> None:
    report = _report()

    exposure = derive_causal_exposure_report("causal-exposure-v1", report)

    assert report.release_disposition == "release_gated"
    assert report.authority == "candidate_only"
    assert exposure.portfolio_id == report.portfolio_id
    assert {item.mechanism_id: item.candidate_exposure_units for item in exposure.exposures} == {
        "ai-capex": 5.0,
        "power-capacity": 1.0,
    }
    assert exposure.total_candidate_exposure_units == 6.0
    assert exposure.content_hash


def test_portfolio_scenario_impact_rejects_double_counted_economic_paths() -> None:
    duplicate = _contribution("impact-4", "run-1", "ai-capex", "capex-to-supplier", -1.0)
    report = _report()
    payload = report.model_dump(mode="json", exclude={"content_hash"})
    payload["contributions"] = (*report.contributions, duplicate)
    payload["declared_net_candidate_impact"] = -5.0

    with pytest.raises(ValueError, match="economic paths"):
        PortfolioScenarioImpactReport.model_validate(payload).sealed()


def test_causal_exposure_rejects_forged_derived_exposure_values() -> None:
    exposure = derive_causal_exposure_report("causal-exposure-v1", _report())
    payload = exposure.model_dump(mode="json", exclude={"content_hash"})
    first_payload = exposure.exposures[0].model_dump(mode="json", exclude={"content_hash"})
    first_payload["candidate_exposure_units"] = 999.0
    forged = CausalPathExposure.model_validate(first_payload).sealed()
    payload["exposures"] = (forged, *exposure.exposures[1:])

    with pytest.raises(ValueError, match="reconcile"):
        CausalExposureReport.model_validate(payload).sealed()
