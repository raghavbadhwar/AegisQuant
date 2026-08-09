# v3B — Quant Research & Multi-Strategy Fund Plan

## Deliverables
1. PIT `UniverseSnapshot` with listings, liquidity, sector, completeness and eligibility reasons.
2. Versioned factor registry: rationale, deterministic formula, lag, horizon, neutralisation, cost/version/history.
3. Diagnostics: IC/rank IC/ICIR, quantiles, long-short, monotonicity, turnover, autocorrelation, decay, cost adjustment, regimes and correlation/crowding.
4. Event CAR study with typed event/source timestamps; deterministic regime and behavioral/graph features.
5. One portfolio-model protocol with equal-weight, inverse-vol, forecast-weighted, shrinkage mean-risk, risk budgeting, HRP, maximum diversification and benchmark tracking; optional skfolio adapter and simple fallback.
6. `FundMandate`, `StrategyPod`, alpha-model/blender, pod policies/budgets, allocator, master target/netting and contribution attribution.
7. qtype/purgedcv/walk-forward/CPCV/PBO/PSR/DSR/cost/perturbation/baseline/ablation experiments, all recorded.

## Gate tests
Universe/factor lags and PIT; diagnostic golden cases; event CARs; purge/embargo; adapter fallback/equivalence; constraints and netting; forecast overlap/uncertainty blending; baseline comparisons; pod/master attribution; same v2 financial path remains intact.
