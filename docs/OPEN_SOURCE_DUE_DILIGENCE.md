# Open-source dependency decisions

- **LangGraph**: the sole agent orchestration runtime; pinned through `uv.lock`.
- **purgedcv**: optional `lab` extra, PyPI 0.1.x (MIT, alpha). Aegis owns timestamp arrays, locked holdout, split validation, normalized reports, and promotion decisions.
- **qtype static analyzer**: optional `lab` extra pinned to MIT repository commit `5277e433a524742c80889af8982377f2bbf8d8f3`. The unrelated PyPI package named `qtype` was explicitly rejected after dependency inspection. Mandatory built-in AST checks remain even if qtype is unavailable.
- **GBrain**: optional protocol adapter only; not installed. Local SQLite is authoritative and revalidates PIT/status/expiry after every projected ID.
- **Scrapling**: typed isolated-worker boundary only; not installed in core. Any future adoption requires a separate dynamic-worker security review.

Agent Reach is an external narrow CLI adapter, not a Python dependency. Core replay does not require any of these optional systems.

- **skfolio**: evaluated at GitHub/PyPI release `0.20.1` (BSD-3-Clause; Python `>=3.10`; active upstream). Not installed for v3B: its mandatory solver/ML/plotting stack (`cvxpy-base`, Clarabel, scikit-learn, Plotly, SciPy) is disproportionate to the eight deterministic models and would make replay depend on solver/version behavior. A typed adapter seam and equivalence/failure tests remain, but the named dependency-free implementation is authoritative. Reconsider only with a measured capability gap and a pinned isolated extra.
