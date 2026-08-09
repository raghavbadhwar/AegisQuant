# v3B — Quant Research & Multi-Strategy Fund Plan

## Accepted entry boundary

v3B starts from independently accepted v3A status commit `bddaeaeb726508ce9daafde2076754f3b3005c8c` (tree `ae35a814cb9854d6a5775e709eb209d09c31f52b`). It may not weaken v2/v3A PIT, evidence, Decimal, authority, deterministic replay, no-live-broker, human-promotion, or clean-release invariants.

## Mandatory deliverables

1. PIT `UniverseSnapshot` with listings, liquidity, market cap, sector/industry, corporate actions, completeness, borrow eligibility, stable eligibility reasons, and an explicit fixed-fixture limitation.
2. Versioned factor registry: rationale, deterministic formula, lookback, lag, universe, neutralisation, horizon, cost assumptions, evaluation history, and version.
3. Diagnostics: IC/rank IC/ICIR, quantiles, long-short, monotonicity, turnover, autocorrelation, sector/size neutrality, subperiod/regime stability, cost adjustment, capacity, decay, and correlation/crowding.
4. Timestamp-correct market-model event studies with CAR windows, bootstrap intervals, source segmentation, surprises, and leakage checks; deterministic regime, behavioural, and graph features that have no order authority.
5. One versioned `PortfolioModel` protocol covering equal weight, inverse volatility, forecast weighted, shrinkage mean-risk, risk budgeting, HRP, maximum diversification, and benchmark tracking. A dependency-free fallback is always available; any optional adapter is explicit and tested.
6. `FundMandate → StrategyPod → AlphaModel → ForecastBlender → PodPortfolioPolicy → PodRiskBudget → FundAllocator → MasterPortfolio → PortfolioProposal`. Contributions remain attributable through deterministic netting. The sole downstream path remains the existing risk gate, order builder, simulated broker, reconciliation, and ledger.
7. qtype plus dynamic future-mutation checks, interval-aware purged walk-forward with embargo, CPCV, PBO, PSR/DSR, cost stress, parameter perturbation, baselines, ablations, and an append-only record of every attempted trial.

## Architectural ownership

- `aegis/contracts/quant.py`: PIT universe, factor, event, regime/feature, portfolio-model, and evaluation contracts.
- `aegis/contracts/strategy.py`: mandate, pod, blend contribution, allocation, master portfolio, and comparison contracts.
- `aegis/quant_research/`: pure universe/factor/diagnostic/event/regime/feature/portfolio-model implementations.
- `aegis/strategy/`: deterministic protocols, blending, pod isolation, allocation, netting, attribution, and conversion to the existing `PortfolioProposal`.
- `aegis/research_lab/strategy_evaluation.py`: leakage-aware validation and predeclared comparison. It cannot activate or promote a model.
- Existing `aegis/fund/run_cycle.py` remains the only financial cycle and the only production caller of risk, orders, and broker execution.

## Predeclared common-sample comparison

The comparison set is immutable before trials: `equal-weight-v1`, `inverse-vol-v1`, `simple-factor-v1`, `fundamental-only-v1`, `quant-only-v1`, and `combined-multistrategy-v1`. Every row uses the same PIT universe snapshots, dates, eligible observations, benchmark, return horizon, capital, constraints, and base/2x/5x cost grids. Losing or rejected rows remain visible.

Primary selection metric is cost-adjusted deflated Sharpe ratio. The combined candidate is **eligible for later human review, never auto-promoted**, only when all integrity gates pass and, on the frozen comparison:

- net annualised Sharpe is at least `0.10` above the best of equal weight, inverse volatility, and simple deterministic factors;
- deflated Sharpe probability is at least `0.50` and PBO is at most `0.50`;
- maximum drawdown is no worse than equal weight;
- turnover is no more than `1.5x` inverse volatility; and
- Sharpe under the `2x` cost grid is non-negative.

Failure yields a typed `rejected` or `abstained` comparison; it does not block release of an honest evaluation system, but the combined model cannot be described or configured as accepted. Complexity is never evidence.

## Gate tests

- PIT/future-mutation invariant universe and factor fixtures; explicit lag/revision behavior and deterministic hashes.
- Hand-computed factor diagnostics, CARs, regimes, feature boundaries, costs, and model weights.
- qtype and dynamic preprocessing gates; interval purge/embargo, CPCV, PBO/PSR/DSR, perturbation and ablation checks.
- Portfolio-proposal self-consistency, final-risk monotonicity, all final constraints, and no alternate order/broker authority.
- Forecast overlap/uncertainty/calibration blending, pod isolation, order-independent allocation/netting, cash conservation, and contribution reconciliation.
- All six predeclared baselines always displayed; every trial retained; optional adapter fallback/equivalence explicit.
- v2 replay bytes, v3A fixtures, the same-cycle structural gate, two isolated v3B comparisons, full static/tests, clean tree, Ponytail review, and independent adversarial audit.

## Optional or deferred

Exact demo pod weights are illustrative. Robust CVaR and adaptive allocators are deferred unless independently justified. `skfolio` is evaluated behind an adapter but is not a mandatory runtime dependency; absence must select a named simple fallback rather than silently changing models.

## Status

**IMPLEMENTATION CANDIDATE — NOT YET ACCEPTED.** The complete deterministic v3B slice and frozen CLI evidence are implemented locally with full static and test gates green. No v3B implementation or combined strategy is accepted until the committed clean-tree release audit, adversarial review, and Ponytail review pass. A quantitatively eligible combined row means only eligible for later human review; it is not selected or promoted.
