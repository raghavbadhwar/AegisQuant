"""AegisQuant command-line interface."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from aegis.brokers import SimBroker
from aegis.contracts import ExperimentRecord, SourceRequest, canonical_json
from aegis.data import FixtureDataClient
from aegis.fund.backtest import backtest_fund
from aegis.fund.ledger import SQLiteRunLedger
from aegis.fund.models import (
    FixtureForecastProvider,
    ForecastProvider,
    MultiStrategyFixtureProvider,
    load_replay_manifest,
)
from aegis.fund.run_cycle import run_cycle
from aegis.fund.spec import load_fund_mandate, load_fund_spec
from aegis.fundamentals import (
    FixtureFundamentalProvider,
    load_fundamental_fixture,
    run_fundamental_graph,
)
from aegis.harness.agent_loader import load_agent_tree
from aegis.harness.graph import LangGraphForecastProvider
from aegis.harness.model_router import ReplayModelProvider
from aegis.harness.skill_loader import load_skill_tree
from aegis.quant_research.demo import (
    demo_event_study,
    demo_factor_diagnostics,
    demo_regime,
    demo_universe,
)
from aegis.quant_research.hashing import build_hashed
from aegis.reporting import dossier_html, dossier_json, dossier_markdown
from aegis.research_lab import (
    ExperimentLedger,
    StrategyReturnSeries,
    evaluate_predeclared_strategies,
)
from aegis.sources import RawStore, SourceGateway, SourcePlanner, SourceRegistry
from aegis.sources.adapters import DirectHTTPConnector

app = typer.Typer(
    name="aegis",
    help="Evidence-first investment research and deterministic paper simulation.",
    no_args_is_help=True,
)
source_app = typer.Typer(help="Governed live-research source intelligence.")
research_app = typer.Typer(help="Standalone institutional research workflows.")
screen_app = typer.Typer(help="Point-in-time universe screening.")
factors_app = typer.Typer(help="Deterministic factor diagnostics.")
events_app = typer.Typer(help="Timestamp-correct event studies.")
regimes_app = typer.Typer(help="Deterministic regime evidence.")
strategy_app = typer.Typer(help="Honest predeclared strategy evaluation.")
fund_app = typer.Typer(help="Multi-strategy simulated fund workflows.")
app.add_typer(source_app, name="sources")
app.add_typer(research_app, name="research")
app.add_typer(screen_app, name="screen")
app.add_typer(factors_app, name="factors")
app.add_typer(events_app, name="events")
app.add_typer(regimes_app, name="regimes")
app.add_typer(strategy_app, name="strategy")
app.add_typer(fund_app, name="fund")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


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


@screen_app.command("run")
def screen_run_command() -> None:
    """Run the frozen PIT universe example; exclusions remain visible."""
    typer.echo(canonical_json(demo_universe()))


@factors_app.command("evaluate")
def factors_evaluate_command() -> None:
    """Run full deterministic factor diagnostics on the frozen panel."""
    typer.echo(canonical_json(demo_factor_diagnostics()))


@events_app.command("study")
def events_study_command() -> None:
    """Run the timestamp-correct frozen market-model CAR study."""
    typer.echo(canonical_json(demo_event_study()))


@regimes_app.command("show")
def regimes_show_command() -> None:
    """Show deterministic six-axis regime evidence."""
    typer.echo(canonical_json(demo_regime()))


@strategy_app.command("evaluate")
def strategy_evaluate_command(
    fixture: Annotated[
        Path, typer.Option(help="Frozen six-way common-sample strategy returns")
    ] = Path("data/fixtures/v3b/strategy_returns.json"),
    ledger: Annotated[Path, typer.Option(help="Append-only experiment ledger")] = Path(
        "run_data/v3b-experiments.sqlite"
    ),
) -> None:
    """Compare all six predeclared strategies without promoting a winner."""
    payload = json.loads(_project_path(fixture).read_text())
    declared_at = datetime.fromisoformat(payload["declared_at"])
    evaluated_at = datetime.fromisoformat(payload["evaluated_at"])
    dates = tuple(date.fromisoformat(value) for value in payload["dates"])
    rows = []
    for number, item in enumerate(payload["rows"], start=1):
        strategy_id = item["strategy_id"]
        experiment = build_hashed(
            ExperimentRecord,
            experiment_id=f"experiment-{strategy_id}",
            candidate_id=f"candidate-{strategy_id}",
            hypothesis_id=f"hypothesis-{strategy_id}",
            code_revision="v3b-frozen-demo",
            tree_hash=payload["tree_hash"],
            data_snapshot_hash=payload["data_snapshot_hash"],
            parameters={"strategy_id": strategy_id},
            dependency_versions={"aegis": "v3b"},
            trial_number=number,
            status="passed",
            created_at=declared_at,
        )
        rows.append(
            StrategyReturnSeries(
                strategy_id=strategy_id,
                common_sample_hash=payload["common_sample_hash"],
                dates=dates,
                data_snapshot_hash=payload["data_snapshot_hash"],
                return_horizon_days=20,
                capital=100_000.0,
                constraints_hash=payload["constraints_hash"],
                benchmark_id="benchmark-spy-v1",
                gross_returns=tuple(item["gross_returns"]),
                turnover=tuple(item["turnover"]),
                experiment=experiment,
            )
        )
    comparison = evaluate_predeclared_strategies(
        rows,
        declared_at,
        evaluated_at,
        ExperimentLedger(_project_path(ledger)),
    )
    typer.echo(canonical_json(comparison))


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
        MultiStrategyFixtureProvider(_project_path(forecast_path), _project_path(evidence_path)),
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
    ledger: Annotated[Path, typer.Option(help="Append-only SQLite run ledger")] = Path(
        "run_data/aegisquant.sqlite"
    ),
) -> None:
    """Backtest through the same cycle used by replay and paper simulation."""
    universe = [ticker.strip() for ticker in tickers.split(",") if ticker.strip()]
    if not universe:
        raise typer.BadParameter("tickers cannot be empty")
    fund = load_fund_spec(_project_path(fund_path))
    result = backtest_fund(
        fund,
        universe,
        date.fromisoformat(start),
        date.fromisoformat(end),
        FixtureDataClient(PROJECT_ROOT / "data/fixtures"),
        SQLiteRunLedger(_project_path(ledger)),
    )
    typer.echo(result.canonical())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
