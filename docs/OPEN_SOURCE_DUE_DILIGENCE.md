# Open-source dependency decisions

- **LangGraph**: the sole agent orchestration runtime; pinned through `uv.lock`.
- **purgedcv**: optional `lab` extra, PyPI 0.1.x (MIT, alpha). Aegis owns timestamp arrays, locked holdout, split validation, normalized reports, and promotion decisions.
- **qtype static analyzer**: optional `lab` extra pinned to MIT repository commit `5277e433a524742c80889af8982377f2bbf8d8f3`. The unrelated PyPI package named `qtype` was explicitly rejected after dependency inspection. Mandatory built-in AST checks remain even if qtype is unavailable.
- **GBrain**: optional protocol adapter only; not installed. Local SQLite is authoritative and revalidates PIT/status/expiry after every projected ID.
- **Scrapling**: typed isolated-worker boundary only; not installed in core. Any future adoption requires a separate dynamic-worker security review.

Agent Reach is an external narrow CLI adapter, not a Python dependency. Core replay does not require any of these optional systems.
