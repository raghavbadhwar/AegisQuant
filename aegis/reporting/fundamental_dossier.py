"""Pure deterministic JSON/Markdown/HTML fundamental-dossier views."""

from __future__ import annotations

import html

from aegis.contracts import FundamentalResearchDossier, canonical_json


def _require_releasable(dossier: FundamentalResearchDossier) -> None:
    if dossier.release_status == "preliminary":
        raise ValueError("preliminary fundamental analysis is not a releasable dossier")


def dossier_json(dossier: FundamentalResearchDossier) -> str:
    _require_releasable(dossier)
    return canonical_json(dossier) + "\n"


def dossier_markdown(dossier: FundamentalResearchDossier) -> str:
    _require_releasable(dossier)
    request = dossier.request
    status = "ABSTAIN" if dossier.abstained else "COMPLETE"
    lines = [
        f"# {request.company_name} ({request.ticker}) - Fundamental Research Dossier",
        "",
        f"As of: `{request.as_of.isoformat()}`",
        f"Dossier ID: `{dossier.dossier_id}`",
        f"Status: `{status}`",
        "",
    ]
    if dossier.abstained:
        lines.extend(["## Abstention", "", dossier.abstain_reason or "Unspecified", ""])
        return "\n".join(lines)
    metrics = dossier.metrics
    valuation = dossier.scenario_valuation
    thesis = dossier.thesis
    assert metrics is not None and valuation is not None and thesis is not None
    roic = metrics.roic if metrics.roic is not None else "N/A"
    metric_calculation_ids = {
        calculation_id.rsplit(":", 1)[-1]: calculation_id
        for calculation_id in metrics.calculation_ids
    }

    def metric_citations(*names: str) -> str:
        return ", ".join(metric_calculation_ids[name] for name in names)

    financial_quality = (
        f"Revenue growth {metrics.revenue_growth:.2%}; operating margin "
        f"{metrics.operating_margin:.2%}; ROIC {roic} "
        f"[calc: {metric_citations('revenue_growth', 'operating_margin', 'roic')}]."
    )
    capital_allocation = (
        f"Acquisition intensity: {metrics.acquisition_intensity:.2%}; "
        f"net buyback yield: {metrics.net_buyback_yield:.2%} "
        f"[calc: {metric_citations('acquisition_intensity', 'net_buyback_yield')}]"
    )
    management = dossier.management
    management_text = (
        f"Matured guidance: {management.matured_count if management else 0}; "
        f"hit rate: {management.hit_rate if management else None} "
        f"[calc: {', '.join(management.calculation_ids) if management else 'unavailable'}]"
    )
    forecast_text = (
        f"Expected excess return: {dossier.alpha_forecast.expected_excess_return:.2%}; "
        f"probability positive: {dossier.alpha_forecast.probability_positive:.2%}; "
        f"confidence: {dossier.alpha_forecast.confidence:.2%}; "
        f"uncertainty: {dossier.alpha_forecast.uncertainty:.2%}; "
        f"horizon: {dossier.alpha_forecast.horizon_days} days "
        "[calc: fundamental-alpha-v1:calibrated-expected-return, "
        "fundamental-alpha-v1:calibrated-probability, "
        "fundamental-alpha-v1:calibrated-confidence]"
    )
    dcf_text = (
        f"Bear/base/bull per-share values: {dossier.dcf['bear'].value_per_share:.2f} / "
        f"{dossier.dcf['base'].value_per_share:.2f} / "
        f"{dossier.dcf['bull'].value_per_share:.2f} "
        f"[calc: {dossier.dcf['bear'].calculation_ids[-1]}, "
        f"{dossier.dcf['base'].calculation_ids[-1]}, "
        f"{dossier.dcf['bull'].calculation_ids[-1]}]"
    )
    reverse_text = "; ".join(
        f"{name}: {result.implied_value} (feasible={result.feasible}) "
        f"[calc: {result.calculation_ids[0]}]"
        for name, result in sorted(dossier.reverse_dcf.items())
    )
    comps = dossier.comparables
    comps_text = (
        f"Range: {comps.implied_value_low:.2f} - {comps.implied_value_high:.2f} "
        f"[calc: {', '.join(comps.calculation_ids)}]"
        if comps
        else "Unavailable"
    )
    scenario_text = (
        f"Probability-weighted value: {valuation.probability_weighted_value:.2f}; "
        f"implied return: {valuation.implied_return:.2%} "
        f"[calc: {', '.join(valuation.calculation_ids)}]"
    )
    operating_forecast_lines = []
    for scenario, operating_forecast in sorted(dossier.forecasts.items()):
        operating_forecast_lines.extend(
            [
                f"### {scenario.title()} operating forecast",
                "",
                "| Year | Revenue | Operating margin | NOPAT | FCFF | Diluted shares |",
                "|---:|---:|---:|---:|---:|---:|",
                *[
                    f"| {period.year} | {period.revenue} | {period.operating_margin:.2%} | "
                    f"{period.nopat} | {period.fcff} | {period.diluted_shares} |"
                    for period in operating_forecast.periods
                ],
                "",
                f"Calculations: `{', '.join(operating_forecast.calculation_ids)}`",
                "",
                "Drivers:",
                *[
                    f"- `{driver.driver_id}` {driver.year} {driver.name}={driver.value} "
                    f"{driver.unit}; evidence=`{', '.join(driver.evidence_ids)}`"
                    for driver in operating_forecast.drivers
                ],
                "",
            ]
        )
    dcf_detail_lines = []
    for scenario, result in sorted(dossier.dcf.items()):
        dcf_detail_lines.extend(
            [
                f"### {scenario.title()} DCF assumptions",
                "",
                *[
                    f"- `{assumption.assumption_id}` {assumption.name}={assumption.value} "
                    f"{assumption.unit}; evidence=`{', '.join(assumption.evidence_ids)}`; "
                    f"calculations=`{', '.join(assumption.calculation_ids)}`"
                    for assumption in result.assumptions
                ],
                "",
                "| Discount rate | Terminal growth | Enterprise value | Equity value/share |",
                "|---:|---:|---:|---:|",
                *[
                    f"| {point.discount_rate:.2%} | {point.terminal_growth:.2%} | "
                    f"{point.enterprise_value} | {point.equity_value_per_share} |"
                    for point in result.sensitivity
                ],
                "",
                f"Calculations: `{', '.join(result.calculation_ids)}`",
                "",
            ]
        )
    sections = [
        ("Business", dossier.business.summary if dossier.business else "Unavailable"),
        ("Industry", dossier.industry.structure if dossier.industry else "Unavailable"),
        ("Financial Quality", financial_quality),
        (
            "Growth",
            f"Growth acceleration: {metrics.growth_acceleration} "
            f"[calc: {metric_citations('growth_acceleration')}].",
        ),
        (
            "Accounting Quality",
            (
                "; ".join(dossier.accounting.findings)
                if dossier.accounting and dossier.accounting.findings
                else "No deterministic warning triggered."
            )
            + " [calc: "
            + metric_citations("accrual_ratio", "sbc_dilution", "acquisition_intensity")
            + "]",
        ),
        (
            "Balance Sheet",
            f"Net debt: {metrics.net_debt:.2f}; current ratio: {metrics.current_ratio} "
            f"[calc: {metric_citations('net_debt', 'current_ratio')}]",
        ),
        ("Capital Allocation", capital_allocation),
        ("Management", management_text),
        ("Forecast and Uncertainty", forecast_text),
        ("Operating Forecasts and Drivers", "\n".join(operating_forecast_lines)),
        ("DCF", dcf_text),
        ("DCF Assumptions and Sensitivities", "\n".join(dcf_detail_lines)),
        ("Reverse DCF", reverse_text),
        ("Comparables", comps_text),
        ("Scenarios", scenario_text),
        (
            "Catalysts",
            "\n".join(f"- {item}" for item in thesis.catalysts) or "- None recorded",
        ),
        ("Risks", "\n".join(f"- {item}" for item in thesis.risks)),
        (
            "Thesis and Invalidation",
            thesis.core_claims[0].statement
            + "\n\n"
            + "\n".join(f"- Invalidate if: {item}" for item in thesis.invalidation_conditions),
        ),
        (
            "Evidence Index",
            "\n".join(
                f"- `{record.evidence_id}` source=`{record.source_id}` "
                f"available_at=`{record.available_at.isoformat()}` "
                f"coordinates=`{record.coordinates}` hash=`{record.content_hash}`"
                for record in (dossier.input_evidence.records if dossier.input_evidence else [])
            ),
        ),
        (
            "Calculation Lineage",
            "\n".join(
                f"- `{item.calculation_id}`: `{item.formula}`; "
                f"inputs(facts={item.input_fact_ids}, calculations={item.input_calculation_ids}, "
                f"assumptions={item.input_assumption_ids}); "
                f"output `{item.output_name}`={item.output_value} {item.unit}; "
                f"hash=`{item.content_hash}`"
                for item in dossier.calculation_lineage
            ),
        ),
        (
            "Known Gaps",
            "\n".join(f"- {item}" for item in dossier.known_gaps) or "- None",
        ),
    ]
    for heading, body in sections:
        lines.extend([f"## {heading}", "", body, ""])
    return "\n".join(lines)


def dossier_html(dossier: FundamentalResearchDossier) -> str:
    return "<html><body><pre>" + html.escape(dossier_markdown(dossier)) + "</pre></body></html>"
