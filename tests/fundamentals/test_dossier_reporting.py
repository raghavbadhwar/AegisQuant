from __future__ import annotations

from pathlib import Path

from aegis.fundamentals import (
    FixtureFundamentalProvider,
    load_fundamental_fixture,
    run_fundamental_graph,
)
from aegis.reporting.fundamental_dossier import dossier_html, dossier_json, dossier_markdown

ROOT = Path(__file__).resolve().parents[2]


def test_dossier_json_markdown_and_html_are_deterministic_and_complete() -> None:
    request, _, _ = load_fundamental_fixture(ROOT / "data/fixtures/fundamentals/cmpd.json")
    dossier = run_fundamental_graph(
        request, FixtureFundamentalProvider(ROOT / "data/fixtures/fundamentals/cmpd.json")
    )
    assert dossier_json(dossier) == dossier_json(dossier)
    markdown = dossier_markdown(dossier)
    html = dossier_html(dossier)
    for section in (
        "Business",
        "Industry",
        "Financial Quality",
        "Accounting Quality",
        "Forecast and Uncertainty",
        "DCF",
        "Reverse DCF",
        "Comparables",
        "Scenarios",
        "Management",
        "Thesis and Invalidation",
        "Evidence Index",
        "Calculation Lineage",
        "Known Gaps",
    ):
        assert f"## {section}" in markdown
    assert dossier.dossier_id in markdown
    assert "<html>" in html and "Fundamental Research Dossier" in html
