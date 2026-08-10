# AegisQuant v6 — Research Institution Architecture

## Status and scope

This is the v6 design authority for the isolated
`upgrade/aegisquant-v6-investment-scientist` branch, based on
`579ddc13c9dae455e87b13720c5b95fa96701096`.

The planned v6 implementation is a candidate-only, verification-first research
institution. This checkout is documentation-only until the TDD slices begin.
The implemented layer will create and organise research records; it cannot
change data splits, holdouts, cost models, trial history, claim-verification
code, promotion, risk, execution, or portfolio authority. It will not make
investment, performance, calibration, or release claims.

The existing v4 causal world model remains an offline candidate input. Its
engineering-only/release-gated evidence cannot be promoted by v6.

No v6 runtime source exists at this documentation milestone. The following
contracts and flows are implementation requirements, not current capability
claims.

## Reused boundaries

| Existing component | v6 use | Boundary retained |
| --- | --- | --- |
| `aegis.research_lab.experiments.ExperimentLedger` | append-only, hash-chained trial persistence | no update/delete and every run is ledgered before evaluation |
| `aegis.contracts.lab.ExperimentRecord` | durable envelope for a sealed v6 run | existing code/tree/data/seed identity remains required |
| `aegis.research_lab.boundaries` | candidate-edit allowlist | agents cannot modify locked evaluation, ledger, risk, execution, or promotion paths |
| `aegis.research_lab.promotion` | independent human-promotion check | v6 never calls it or produces a promotion decision |
| `aegis.harness.CapabilityBroker` | typed role/tool grants and budgets | research roles cannot access broker, execution, risk, or promotion tools |
| `aegis.research_planner` | read-only bounded research-value ranking | a recommendation never starts, approves, or pays for research |
| `aegis.harness.graph` | existing replay-only LangGraph research harness | no network in replay/historical and model failure abstains |
| `apps/dashboard.py` | later read-only observer pattern | no dashboard mutation or command authority |

No new database, orchestration framework, model provider, or dependency is
introduced. The first vertical slice uses existing SQLite, Pydantic, LangGraph,
Typer, and Streamlit only.

## Domain model

All new persisted/public v6 records inherit `CandidateContractModel`, are
frozen with `extra="forbid"`, reject invalid `model_copy()` updates, and carry a
deterministic SHA-256 content address. A content address is not authentication;
an original-record claim requires the existing append-only ledger and a retained
receipt/reference.

Every research assertion is bound through `ResearchEvidenceBinding`: one `as_of`,
validated `SourceProvenanceReference` items from the existing traceability
module, one `SnapshotReference`, and a new
`ResearchArtifactReceiptReference(receipt_id, artifact_id, artifact_content_hash,
recorded_at)`. The source references must satisfy `available_at <= as_of`; the
snapshot must satisfy `snapshot.as_of <= as_of`; and the retained receipt must
match the sealed research artifact before an original-record assertion is
rendered. The receipt is a reference to separately retained governed storage,
not a local authenticity claim. `Hypothesis`, `NoveltyReport`, `ExperimentPlan`,
`ExperimentRun`, `NegativeResult`, `ResearchClaim`, `VerificationPackage`, and
`ResearchPostmortem` each carry the same revalidated binding.

`aegis.research_lab.science` will provide these closed contracts:

| Contract | Purpose and mandatory bindings |
| --- | --- |
| `ResearchBudget` | finite compute/data/review costs and a fixed total cap |
| `ResearchProgramme` | mandate, owner identity, `ResearchEvidenceBinding`, budget, max team/depth limits, decision-value input, status and sealed hypothesis-family IDs |
| `HypothesisFamily` / `Hypothesis` | at least two competing, falsifiable hypotheses; stable `mechanism_id`, predictions, assumptions, known failure condition and evidence binding |
| `ResearchTeam` / `ResearchTreeNode` / `ResearchTree` | bounded discovery/replication/adversarial teams, parentage, depth, critique-before-run, cost ceiling, and explicit replication exception for duplicate hypotheses |
| `NoveltyReport` | evidence-bound internal-prior record; it must include the exact deterministic surfaced negative-result IDs and never invent literature support |
| `ExperimentPlan` | preregistration, sealed data snapshot, split/metric/baseline/ablation/stop-rule identifiers, locked fields and author identity |
| `ExperimentRun` | one deterministic run bound to a sealed plan, code/tree/data hashes, seeds, lifecycle timestamps, and experiment-ledger record |
| `ReplicationRun` | independent identity and separate run bound to an original run; it cannot replicate itself |
| `NegativeResult` | evidence-bound rejected/inconclusive result, causal/economic/operational reason, re-open condition, source run hash, and `mechanism_id`/assumption IDs |
| `ResearchClaim` | candidate, limited, verified, rejected, or abstained claim; no factual conclusion without a package |
| `VerificationPackage` | preregistration, run(s), replication(s), reviewer, approver, limits, and claim-strength ceiling |
| `ResearchContribution` | non-overlapping allocation to one mechanism path; aggregate totals reconcile exactly |
| `ResearchPostmortem` | negative/positive/inconclusive review with retained limitations |
| `ResearchPortfolioCandidate` / `ResearchPortfolio` | finite validity, decision-value, novelty, strategic-fit, compute/data/review/redundancy costs, deadline and read-only ranking/stop; no spending or execution authority |

The aggregate validators reconstruct every nested contract at their public
boundary, require sealed child hashes, reject duplicate IDs/paths, and enforce
distinct proposer, verifier, and approver identities. A verified claim requires
an independent replication. A limited claim is explicitly labelled and cannot
be rendered as verified. An abstention has no conclusion fields.

`ResearchTree` rejects an active duplicate `hypothesis_id` unless the node is
owned by a replication team and references its original node. Every child has
one parent, `depth == parent.depth + 1`, `depth <= programme.max_tree_depth`,
and a critique receipt before an `ExperimentPlan` can use it. The sum of active
node compute costs cannot exceed either team or programme caps. `ResearchTeam`
members cannot be reviewers/approvers for their own output.

Negative-result surfacing is deliberately simple and deterministic. For a new
hypothesis, `ResearchArchive.surfaced_negative_results()` considers only prior
negative/inconclusive records in the same programme with an identical
`mechanism_id` or a non-empty intersection of declared assumption IDs. It sorts
by exact-mechanism match descending, shared-assumption count descending, then
`negative_result_id` ascending. A novelty report must bind exactly that ordered
tuple. No embedding, LLM, fuzzy-search, or external literature lookup is used.

## Research flow

```text
sealed programme + budget
  -> competing sealed hypotheses + novelty report
  -> bounded team + progressive tree node + recorded pre-compute critique
  -> immutable preregistered experiment plan
  -> sealed deterministic run recorded in existing ExperimentLedger
  -> replication / negative result / adversarial review
  -> bounded verification package
  -> read-only research portfolio rank or documented stop
  -> read-only report constrained to package strength
```

`record_experiment_run()` is the shared persistence path. It creates the
existing `ExperimentRecord` from an already-sealed v6 run and appends it before
returning any result. Its `parameters` field stores only the canonical v6 run
payload and its content hash; loading revalidates both layers. No direct SQLite
write is exposed in v6 code.

The first planned v6 vertical slice will support registered deterministic
fixture evaluations only. It will accept no agent-generated shell, Python,
patch, network, or broker command. An unregistered or unavailable executor will
produce a typed abstention and no run. This is deliberate: a general code
sandbox is not claimed until an independently approved isolation backend exists.

## Role and authority model

Research roles are typed identities, not prompt text. `V6_ROLE_TOOL_GRANTS`
will be a closed allowlist consulted before `CapabilityBroker`; the broker then
enforces registered-skill, mode, budget, and global forbidden-prefix checks.
The planned logical grant matrix is:

| Role | Only permitted v6 logical capabilities |
| --- | --- |
| director | `science.programme.plan`, `science.portfolio.rank` |
| hypothesis architect | `science.hypothesis.propose`, `science.tree.propose` |
| novelty auditor | `science.archive.search`, `science.novelty.record` |
| experiment designer | `science.experiment.preregister` |
| quant research engineer | `science.fixture.evaluate` |
| statistician | `science.experiment.review` |
| replication team | `science.replication.record` |
| adversarial reviewer | `science.review.adversarial` |
| claim verifier | `science.claim.verify` |
| archivist | `science.archive.record`, `science.postmortem.record` |

The logical capabilities are deterministic in-process record operations, not
external tools. `authorize_v6_research_tool()` denies every mapping omission,
all broker/execution/risk/promotion prefixes, source acquisition, and every
capability not in the role row. The proposer cannot verify/approve its work;
the verifier cannot approve; no role receives a capital-critical capability.

The model/harness may propose records only. Deterministic validators enforce
the graph, ledger binding, ordering, and identity separation. Every unavailable
model/tool condition is a typed abstention, never a fallback conclusion.

## Read-only observation

`science_report_view()` will render only sealed programme/archive/package data
and will use the verification package's strength and limitations verbatim. A
later `science` Typer group and the existing Streamlit `Research Lab` tab may
load an explicitly supplied read-only science ledger; neither creates records,
starts experiments, approves claims, or crosses into the fund path.

`ResearchPortfolioCandidate` computes the declared bounded research priority
score directly from `expected_validity * decision_value * novelty * strategic_fit`
over `compute_cost + data_cost + review_cost + redundancy_penalty`. Every term
is finite and non-negative; zero denominator is denied. Existing
`ResearchAction`/VOI output is retained only as an optional no-positive-VOI
cross-check, not as the allocator. Stable ordering uses score descending then
programme ID. `ResearchPortfolio` must emit exactly one read-only selection set
or a stop reason: non-positive VOI, redundancy, budget, deadline, robustness,
or non-decision-changing uncertainty.

## Explicit non-goals

- no live broker, orders, weights, risk decision, capital allocation, or promotion output;
- no unbounded agent loops, self-modifying code, hidden trial sweep, remote worker, or network I/O in replay/historical mode;
- no paper, data-source, calibration, accuracy, novelty, or investment claim from local fixtures;
- no v7 strategy genome/ecology, v8 authority, or v9 federation work.
