"""AegisQuant command-line interface."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from aegis.brokers import SimBroker
from aegis.contracts import SourceRequest, canonical_json
from aegis.data import FixtureDataClient
from aegis.fund.backtest import backtest_fund
from aegis.fund.ledger import SQLiteRunLedger
from aegis.fund.models import FixtureForecastProvider, ForecastProvider, load_replay_manifest
from aegis.fund.run_cycle import run_cycle
from aegis.fund.spec import load_fund_spec
from aegis.harness.agent_loader import load_agent_tree
from aegis.harness.graph import LangGraphForecastProvider
from aegis.harness.model_router import ReplayModelProvider
from aegis.harness.skill_loader import load_skill_tree
from aegis.sources import RawStore, SourceGateway, SourcePlanner, SourceRegistry
from aegis.sources.adapters import DirectHTTPConnector

app = typer.Typer(
    name="aegis",
    help="Evidence-first investment research and deterministic paper simulation.",
    no_args_is_help=True,
)
source_app = typer.Typer(help="Governed live-research source intelligence.")
app.add_typer(source_app, name="sources")
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
        SimBroker(fund.capital),
        data_client,
        provider,
        SQLiteRunLedger(_project_path(ledger)),
    )
    typer.echo(record.canonical())


@app.command()
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
