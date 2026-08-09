"""AegisQuant command-line interface."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from aegis.brokers import SimBroker
from aegis.contracts import SourceRequest, canonical_json
from aegis.data import FixtureDataClient
from aegis.fund.backtest import backtest_fund
from aegis.fund.ledger import SQLiteRunLedger
from aegis.fund.models import (
    FixtureForecastProvider,
    ForecastProvider,
    HistoricalMultiStrategyFixtureProvider,
    MultiStrategyFixtureProvider,
    load_historical_artifact_manifest,
    load_replay_manifest,
)
from aegis.fund.run_cycle import run_cycle
from aegis.fund.spec import load_fund_configuration, load_fund_mandate, load_fund_spec
from aegis.fundamentals import (
    FixtureFundamentalProvider,
    load_fundamental_fixture,
    run_fundamental_graph,
)
from aegis.harness.agent_loader import load_agent_tree
from aegis.harness.graph import LangGraphForecastProvider
from aegis.harness.model_router import ReplayModelProvider
from aegis.harness.skill_loader import load_skill_tree
from aegis.pit_data.builder import bootstrap as bootstrap_pit
from aegis.pit_data.builder import ingest_sec, normalize_nport
from aegis.pit_data.ledger import PITAvailabilityLedger
from aegis.pit_data.models import PITArtifact, SecurityMasterRecord
from aegis.pit_data.nport import NPortHolding, acquire_nport_archive
from aegis.pit_data.sec import SecPITClient
from aegis.quant_research.demo import (
    demo_event_study,
    demo_factor_diagnostics,
    demo_regime,
    demo_universe,
)
from aegis.reporting import dossier_html, dossier_json, dossier_markdown
from aegis.sources import RawStore, SourceGateway, SourcePlanner, SourceRegistry
from aegis.sources.adapters import DirectHTTPConnector

app = typer.Typer(
    name="aegis",
    help="Evidence-first investment research and deterministic paper simulation.",
    no_args_is_help=True,
)
source_app = typer.Typer(help="Governed live-research source intelligence.")
research_app = typer.Typer(help="Standalone institutional research workflows.")
demo_app = typer.Typer(
    help="Frozen no-network illustrative v3B examples; not production screening."
)
strategy_app = typer.Typer(help="Honest predeclared strategy evaluation.")
fund_app = typer.Typer(help="Multi-strategy simulated fund workflows.")
pit_app = typer.Typer(help="Real-source, availability-gated historical PIT dataset builder.")
app.add_typer(source_app, name="sources")
app.add_typer(research_app, name="research")
app.add_typer(demo_app, name="demo")
app.add_typer(strategy_app, name="strategy")
app.add_typer(fund_app, name="fund")
app.add_typer(pit_app, name="pit")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@pit_app.command("bootstrap")
def pit_bootstrap(
    root: Annotated[Path, typer.Option("--root", help="Local PIT lake directory")] = Path(
        "data/pit"
    ),
) -> None:
    """Initialize an empty local PIT lake without acquiring data."""
    typer.echo(str(bootstrap_pit(_project_path(root))))


@pit_app.command("ingest-sec")
def pit_ingest_sec(
    tickers: Annotated[list[str], typer.Argument(help="SEC-listed tickers to ingest")],
    user_agent: Annotated[
        str, typer.Option("--sec-user-agent", help="SEC-compliant contact-bearing User-Agent")
    ],
    root: Annotated[Path, typer.Option("--root", help="Local PIT lake directory")] = Path(
        "data/pit"
    ),
    filing_start: Annotated[
        str | None, typer.Option("--from", help="Earliest filing date (YYYY-MM-DD)")
    ] = None,
    filing_end: Annotated[
        str | None, typer.Option("--to", help="Latest filing date (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Acquire official SEC filing artifacts; records are content-addressed and immutable."""
    artifacts = ingest_sec(
        _project_path(root),
        user_agent,
        tuple(tickers),
        filing_start=date.fromisoformat(filing_start) if filing_start else None,
        filing_end=date.fromisoformat(filing_end) if filing_end else None,
    )
    typer.echo(
        canonical_json(
            {
                "artifact_count": len(artifacts),
                "artifact_ids": [item.artifact_id for item in artifacts],
            }
        )
    )


@pit_app.command("ingest-nport")
def pit_ingest_nport(
    period: Annotated[str, typer.Option("--period", help="Official SEC quarterly period, YYYYQ#")],
    user_agent: Annotated[
        str, typer.Option("--sec-user-agent", help="SEC-compliant contact-bearing User-Agent")
    ],
    root: Annotated[Path, typer.Option("--root", help="Local PIT lake directory")] = Path(
        "data/pit"
    ),
) -> None:
    """Raw-capture one official N-PORT quarterly archive before any normalization."""
    lake = bootstrap_pit(_project_path(root))
    receipt = acquire_nport_archive(SecPITClient(user_agent, RawStore(lake / "raw")), period)
    typer.echo(canonical_json(receipt))


@pit_app.command("normalize-nport")
def pit_normalize_nport(
    archive: Annotated[Path, typer.Option("--archive", help="Locally captured SEC N-PORT ZIP")],
    raw_artifact_id: Annotated[
        str, typer.Option("--raw-artifact-id", help="Raw archive provenance ID")
    ],
    series: Annotated[list[str], typer.Option("--series", help="Explicit bounded SEC series ID")],
    root: Annotated[Path, typer.Option("--root", help="Local PIT lake directory")] = Path(
        "data/pit"
    ),
) -> None:
    """Normalize selected N-PORT fund holdings under a conservative availability policy."""
    rows = normalize_nport(
        _project_path(root),
        _project_path(archive),
        raw_artifact_id=raw_artifact_id,
        series_ids=frozenset(series),
    )
    typer.echo(canonical_json({"holding_count": len(rows)}))


@pit_app.command("build-snapshot")
def pit_build_snapshot(
    at: Annotated[str, typer.Option("--at", help="Timezone-aware ISO-8601 simulation timestamp")],
    universe: Annotated[list[str], typer.Option("--universe", help="Ticker/entity universe")],
    root: Annotated[Path, typer.Option("--root", help="Local PIT lake directory")] = Path(
        "data/pit"
    ),
) -> None:
    """Seal an offline historical information world from only previously available artifacts."""
    lake = _project_path(root)
    ledger_path = lake / "normalized" / "artifact_ledger.jsonl"
    if not ledger_path.exists():
        raise typer.BadParameter("PIT artifact ledger does not exist; run pit ingest-sec first")
    artifacts = tuple(
        PITArtifact.model_validate_json(row) for row in ledger_path.read_text().splitlines() if row
    )
    security_path = lake / "normalized" / "security_master.jsonl"
    securities = (
        tuple(
            SecurityMasterRecord.model_validate_json(row)
            for row in security_path.read_text().splitlines()
            if row
        )
        if security_path.exists()
        else ()
    )
    try:
        simulation_at = datetime.fromisoformat(at)
    except ValueError as exc:
        raise typer.BadParameter("--at must be ISO-8601") from exc
    holdings_path = lake / "normalized" / "nport_holdings.jsonl"
    holdings = (
        tuple(
            NPortHolding.model_validate_json(row)
            for row in holdings_path.read_text().splitlines()
            if row
        )
        if holdings_path.exists()
        else ()
    )
    snapshot = PITAvailabilityLedger(artifacts, securities).write_snapshot(
        lake / "snapshots",
        simulation_at,
        tuple(universe),
        dataset_version="sec-edgar-v1",
        fund_holdings=holdings,
    )
    typer.echo(str(snapshot))


@pit_app.command("verify-snapshot")
def pit_verify_snapshot(
    path: Annotated[Path, typer.Argument(help="Local immutable snapshot directory")],
) -> None:
    """Verify the central no-future-artifact and manifest-lineage release checks."""
    from aegis.pit_data.ledger import load_snapshot

    manifest, artifacts = load_snapshot(_project_path(path))
    typer.echo(
        canonical_json(
            {
                "simulation_at": manifest.simulation_at,
                "artifact_count": len(artifacts),
                "manifest_hash": manifest.manifest_hash,
            }
        )
    )


@source_app.command("plan")
def source_plan(
    request_path: Annotated[Path, typer.Argument(help="Typed SourceRequest JSON")],
    registry_path: Annotated[
        Path, typer.Option("--registry", help="Versioned source registry directory")
    ] = Path("configs/sources"),
) -> None:
    """Plan a mode-gated, official-first acquisition without fetching."""
    request = SourceRequest.model_validate_json(_project_path(request_path).read_bytes())
    registry = SourceRegistry.load(_project_path(registry_path))
    typer.echo(canonical_json(SourcePlanner(registry).plan(request)))


@source_app.command("acquire")
def source_acquire(
    request_path: Annotated[Path, typer.Argument(help="Typed SourceRequest JSON")],
    url: Annotated[str, typer.Option(help="Explicit approved HTTPS URL")],
    registry_path: Annotated[
        Path, typer.Option("--registry", help="Versioned source registry directory")
    ] = Path("configs/sources"),
    raw_store: Annotated[
        Path, typer.Option("--raw-store", help="Immutable raw capture directory")
    ] = Path("data/lake/raw"),
) -> None:
    """Acquire one approved live-research URL through the raw-first gateway."""
    request = SourceRequest.model_validate_json(_project_path(request_path).read_bytes())
    registry = SourceRegistry.load(_project_path(registry_path))
    planner = SourcePlanner(registry)
    plan = planner.plan(request)
    if plan.acquisition_methods != ["direct-http"]:
        raise typer.BadParameter("this command supports a single direct-http plan")
    connector = DirectHTTPConnector(lambda _request, _manifest: url)
    gateway = SourceGateway(
        registry,
        planner,
        RawStore(_project_path(raw_store)),
        {"direct-http": connector},
    )
    result, evidence = gateway.acquire(request)
    typer.echo(canonical_json({"result": result, "evidence": evidence}))


@research_app.command("company")
def research_company_command(
    ticker: Annotated[str, typer.Argument(help="Company ticker")],
    as_of: Annotated[str, typer.Option(help="Point-in-time date (YYYY-MM-DD)")],
    fixture: Annotated[
        Path | None,
        typer.Option(help="Frozen fundamental fixture; defaults to the ticker fixture"),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: json, markdown, or html"),
    ] = "markdown",
    output: Annotated[Path | None, typer.Option(help="Optional local output path")] = None,
) -> None:
    """Generate a PIT, calculation-backed company dossier without running a fund."""
    fixture_path = _project_path(
        fixture or Path(f"data/fixtures/fundamentals/{ticker.lower()}.json")
    )
    request, _, _ = load_fundamental_fixture(fixture_path)
    if request.ticker != ticker.upper() or request.as_of.date().isoformat() != as_of:
        raise typer.BadParameter("ticker/as-of must match the frozen point-in-time fixture")
    dossier = run_fundamental_graph(request, FixtureFundamentalProvider(fixture_path))
    if output_format == "json":
        rendered = dossier_json(dossier)
    elif output_format == "markdown":
        rendered = dossier_markdown(dossier)
    elif output_format == "html":
        rendered = dossier_html(dossier)
    else:
        raise typer.BadParameter("format must be json, markdown, or html")
    if output is not None:
        _project_path(output).write_text(rendered)
    else:
        typer.echo(rendered, nl=False)


@demo_app.command("screen")
def screen_run_command() -> None:
    """Illustrate a frozen PIT universe; not production screening."""
    typer.echo(canonical_json(demo_universe()))


@demo_app.command("factors")
def factors_evaluate_command() -> None:
    """Illustrate factor diagnostics on a small frozen panel."""
    typer.echo(canonical_json(demo_factor_diagnostics()))


@demo_app.command("events")
def events_study_command() -> None:
    """Illustrate a timestamp-correct frozen market-model CAR study."""
    typer.echo(canonical_json(demo_event_study()))


@demo_app.command("regimes")
def regimes_show_command() -> None:
    """Illustrate deterministic six-axis regime evidence."""
    typer.echo(canonical_json(demo_regime()))


@strategy_app.command("evaluate")
def strategy_evaluate_command() -> None:
    """Refuse fixture-vector eligibility until receipt-derived comparison is supplied."""
    raise typer.BadParameter(
        "strategy eligibility requires receipt-derived historical comparisons; "
        "hand-authored return fixtures are not an authority"
    )


@fund_app.command("run")
def institutional_fund_run_command(
    case_path: Annotated[Path, typer.Option("--case", help="Replay case JSON manifest")] = Path(
        "data/fixtures/cases/nvda_earnings_case.json"
    ),
    mandate_path: Annotated[
        Path, typer.Option("--mandate", help="Hash-bound institutional mandate YAML")
    ] = Path("configs/funds/aegis-institutional-demo-v3.yaml"),
    forecast_path: Annotated[
        Path, typer.Option("--forecasts", help="Sealed multi-model forecast fixture")
    ] = Path("data/fixtures/v3b/multi_strategy_forecasts.json"),
    evidence_path: Annotated[
        Path, typer.Option("--evidence", help="Sealed evidence fixture")
    ] = Path("data/fixtures/evidence/replay_evidence.jsonl"),
    quant_bundle: Annotated[
        Path, typer.Option("--quant-bundle", help="Sealed same-case quant research bundle")
    ] = Path("data/fixtures/v3b/quant_research_bundle.json"),
    ledger: Annotated[Path, typer.Option(help="Append-only SQLite run ledger")] = Path(
        "run_data/aegisquant-v3b.sqlite"
    ),
) -> None:
    """Run the attributed v3B master target through the sole existing cycle."""
    manifest = load_replay_manifest(_project_path(case_path))
    case = manifest.research_case()
    fund = load_fund_mandate(_project_path(mandate_path))
    record = run_cycle(
        fund,
        case,
        SimBroker(float(fund.capital)),
        FixtureDataClient(PROJECT_ROOT / "data/fixtures"),
        MultiStrategyFixtureProvider(
            _project_path(forecast_path),
            _project_path(evidence_path),
            _project_path(quant_bundle),
        ),
        SQLiteRunLedger(_project_path(ledger)),
    )
    typer.echo(record.canonical())


@app.command()
def replay(
    case_path: Annotated[Path, typer.Argument(help="Replay case JSON manifest")],
    ledger: Annotated[Path, typer.Option(help="Append-only SQLite run ledger")] = Path(
        "run_data/aegisquant.sqlite"
    ),
    desk: Annotated[str, typer.Option(help="Research provider: graph or fixture")] = "graph",
) -> None:
    """Run a deterministic, network-denied, no-key replay cycle."""
    manifest = load_replay_manifest(_project_path(case_path))
    case = manifest.research_case()
    fund = load_fund_spec(_project_path(manifest.fund_path))
    data_client = FixtureDataClient(PROJECT_ROOT / "data/fixtures")
    fixture_provider = FixtureForecastProvider(
        _project_path(manifest.forecast_fixture), _project_path(manifest.evidence_fixture)
    )
    provider: ForecastProvider
    if desk == "graph":
        preflight = fixture_provider.research(
            case, data_client.latest_snapshot(case.tickers, case.as_of)
        )
        provider = LangGraphForecastProvider(
            ReplayModelProvider(_project_path(manifest.agent_output_fixture), case.case_id),
            load_skill_tree(PROJECT_ROOT / "skills"),
            load_agent_tree(PROJECT_ROOT / "aegis/agents"),
            preflight.evidence,
        )
    elif desk == "fixture":
        provider = fixture_provider
    else:
        raise typer.BadParameter("desk must be 'graph' or 'fixture'")
    record = run_cycle(
        fund,
        case,
        SimBroker(float(fund.capital)),
        data_client,
        provider,
        SQLiteRunLedger(_project_path(ledger)),
    )
    typer.echo(record.canonical())


@app.command()
@fund_app.command("backtest")
def backtest(
    fund_path: Annotated[Path, typer.Option("--fund", help="Fund mandate YAML")],
    tickers: Annotated[str, typer.Option(help="Comma-separated ticker universe")],
    start: Annotated[str, typer.Option(help="First historical date (YYYY-MM-DD)")],
    end: Annotated[str, typer.Option(help="Last historical date (YYYY-MM-DD)")],
    historical_artifacts: Annotated[
        Path | None,
        typer.Option("--historical-artifacts", help="Sealed local institutional artifact manifest"),
    ] = None,
    data_root: Annotated[
        Path,
        typer.Option(
            "--data-root", help="Local sealed fixture directory; network is always forbidden"
        ),
    ] = Path("data/fixtures"),
    ledger: Annotated[Path, typer.Option(help="Append-only SQLite run ledger")] = Path(
        "run_data/aegisquant.sqlite"
    ),
) -> None:
    """Backtest through the same cycle used by replay and paper simulation."""
    universe = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
    if not universe:
        raise typer.BadParameter("tickers cannot be empty")
    fund = load_fund_configuration(_project_path(fund_path))
    provider = None
    if historical_artifacts is not None:
        provider = HistoricalMultiStrategyFixtureProvider(
            load_historical_artifact_manifest(_project_path(historical_artifacts))
        )
    result = backtest_fund(
        fund,
        universe,
        date.fromisoformat(start),
        date.fromisoformat(end),
        FixtureDataClient(_project_path(data_root)),
        SQLiteRunLedger(_project_path(ledger)),
        provider,
    )
    typer.echo(result.canonical())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
