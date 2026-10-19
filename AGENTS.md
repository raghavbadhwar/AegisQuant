# AegisQuant Engineering Rules

1. Research, backtest, replay, and simulated paper execution only. Never add a live broker.
2. LLM/agent code may produce typed research artifacts and forecasts; deterministic code alone sizes, risk-checks, and submits simulated orders.
3. Historical mode is network-denied and may only use evidence/memory with `available_at <= as_of`.
4. Data-integrity failures halt. Model failures become explicit abstentions.
5. Every material forecast claim cites evidence IDs; exact values retain field/table provenance.
6. The risk policy is immutable within a run and every clamp/decision is ledgered.
7. Use the same `run_cycle` implementation for replay, historical backtest, and paper simulation.
8. Learning output is candidate-only. Promotion always requires a human decision.
9. Prefer the smallest explicit implementation; do not remove validation, provenance, audit, or safety controls as “simplification.”
10. Before release run pytest, Ruff, mypy, replay determinism, security tests, and ledger reconciliation.
