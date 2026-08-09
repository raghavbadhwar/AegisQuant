from __future__ import annotations

from pathlib import Path

from aegis.research_lab.static_checks import BuiltInQuantChecker, QTypeAdapter

ROOT = Path(__file__).resolve().parents[2]
MODULES = tuple(
    sorted(
        (*((ROOT / "aegis/quant_research").glob("*.py")), *((ROOT / "aegis/strategy").glob("*.py")))
    )
)


def test_every_v3b_quant_module_passes_builtin_and_qtype_preflight() -> None:
    qtype = QTypeAdapter(required=True)
    for path in MODULES:
        assert BuiltInQuantChecker.check(path.read_text()) == (), path
        assert qtype.check(path) == (), path
