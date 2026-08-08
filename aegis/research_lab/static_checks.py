"""Mandatory built-in time-leak checks with an optional qtype adapter."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StaticDiagnostic:
    rule_id: str
    line: int
    message: str


class BuiltInQuantChecker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.diagnostics: list[StaticDiagnostic] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "shift" and node.args:
            argument = node.args[0]
            if (
                isinstance(argument, ast.UnaryOp)
                and isinstance(argument.op, ast.USub)
                and isinstance(argument.operand, ast.Constant)
            ):
                self.diagnostics.append(
                    StaticDiagnostic("AQ001", node.lineno, "negative shift leaks future data")
                )
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name in {"lead", "peek_future", "look_forward"}:
            self.diagnostics.append(
                StaticDiagnostic("AQ002", node.lineno, f"future function is forbidden: {name}")
            )
        self.generic_visit(node)

    @classmethod
    def check(cls, source: str) -> tuple[StaticDiagnostic, ...]:
        checker = cls()
        checker.visit(ast.parse(source))
        return tuple(checker.diagnostics)


class QTypeAdapter:
    def __init__(self, required: bool = False) -> None:
        self.required = required

    def check(self, path: str | Path) -> tuple[StaticDiagnostic, ...]:
        executable = shutil.which("qtype")
        if executable is None:
            if self.required:
                raise RuntimeError("qtype is required by the evaluation suite but unavailable")
            return ()
        completed = subprocess.run(
            [executable, "check", str(Path(path).resolve()), "--format", "json"],
            shell=False,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError("qtype preflight failed to execute")
        payload = json.loads(completed.stdout or b"[]")
        if not isinstance(payload, list):
            raise RuntimeError("qtype returned an invalid report")
        return tuple(
            StaticDiagnostic(
                rule_id=str(item["rule_id"]),
                line=int(item["line"]),
                message=str(item["message"]),
            )
            for item in payload
        )
