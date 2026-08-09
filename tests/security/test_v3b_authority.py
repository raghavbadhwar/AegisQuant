from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = tuple(sorted((ROOT / "aegis").rglob("*.py")))


def _call_count(attribute: str) -> int:
    return sum(
        1
        for path in PRODUCTION
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == attribute)
            or (isinstance(node.func, ast.Name) and node.func.id == attribute)
        )
    )


def test_existing_run_cycle_remains_the_only_execution_authority() -> None:
    definitions = [
        (path, node)
        for path in PRODUCTION
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_cycle"
    ]
    assert [(path.relative_to(ROOT), node.name) for path, node in definitions] == [
        (Path("aegis/fund/run_cycle.py"), "run_cycle")
    ]
    assert _call_count("execute_batch") == 1
    assert _call_count("build_orders") == 1


def test_quant_and_strategy_modules_have_no_order_broker_or_risk_authority() -> None:
    forbidden = {"aegis.brokers", "aegis.fund.execution", "aegis.risk"}
    for directory in (ROOT / "aegis/quant_research", ROOT / "aegis/strategy"):
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module is not None
            } | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            assert not any(
                module == prefix or module.startswith(prefix + ".")
                for module in imports
                for prefix in forbidden
            ), path
