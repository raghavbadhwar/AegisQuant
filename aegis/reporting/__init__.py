"""Read-only reporting adapters and view models."""

from .fundamental_dossier import dossier_html, dossier_json, dossier_markdown
from .ledger_reader import ReadOnlyRunLedger

__all__ = ["ReadOnlyRunLedger", "dossier_html", "dossier_json", "dossier_markdown"]
