#!/usr/bin/env bash
set -euo pipefail
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run python scripts/export_contract_schemas.py --check
uv run pytest -q
scripts/test-postgres-migration.sh
