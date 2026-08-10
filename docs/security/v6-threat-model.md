# v6 Threat Model — Verification-First Research

## Assets and trust boundary

The protected assets are sealed research artefacts, PIT snapshot references,
trial history, identity separation, bounded research budgets, candidate source
code, and existing risk/execution/promotion controls. Prompts, model output,
source text, local fixtures, and incoming JSON are untrusted input.

v6 is an offline candidate-research layer. It has no broker credentials, live
market connection, order capability, risk-policy write, promotion capability,
or general code-execution capability. `CapabilityBroker` remains the runtime
grant authority; Markdown agents and reports are not authority.

## Threats and required controls

| Threat | Control | Test evidence |
| --- | --- | --- |
| hidden trial or replaced history | append every run through `ExperimentLedger` before result; verify its commitment chain on reads | failed-run visibility, tamper, and missing-ledger tests |
| post-result plan alteration | frozen sealed `ExperimentPlan`, lifecycle ordering, locked-field/hash validation | direct/model-copy and post-run mutation tests |
| holdout/data leakage | bind plan/run to sealed PIT snapshot and existing split identifiers; reject future `available_at` data | future/PIT and split-substitution tests |
| forged original-record provenance | require source/snapshot cutoff checks plus matching separately retained research-artifact receipt reference | forged receipt, hash, and snapshot tests |
| self-verification or self-approval | require pairwise-distinct proposer, verifier, and approver identities | role-collision tests |
| fabricated/overstated research claim | report derives from sealed package; verified requires independent replication; limited/abstained statuses retain limits | claim-ceiling and self-replication tests |
| deletion/erasure of failures | immutable ledger plus archive records; no delete/update API | negative-result/search and ledger integrity tests |
| duplicate or runaway research branch | sealed team/tree parentage, explicit replication exception, depth/cost limits, and critique-before-run | duplicate/depth/budget/critique tests |
| model/prompt injection | treat generated content as data; typed validation only; no prompt-derived tool authority | malformed artifact and denied capability tests |
| capability escalation | closed v6 role-to-tool allowlist before `CapabilityBroker` forbidden prefixes and candidate path boundary | per-role broker/risk/promotion/source denial tests |
| arbitrary code or shell execution | only registered deterministic fixture evaluator identifiers; unknown executor abstains | unsupported-executor/no-subprocess tests |
| network leakage in historical/replay | no source connector import/call in science module; retain mode gates | static import and denial tests |
| budget/cost manipulation | finite component amounts, exact total/reconciliation, bounded VOI selection | overflow/forged-total tests |
| replacement of content-addressed records | nested revalidation and retained ledger/receipt reference | forged child/hash and reload tests |

## Security decisions

The initial v6 implementation does not present a general sandbox as secure.
It never runs agent-provided code. If no registered deterministic evaluator is
available, it produces an explicit abstention and does not create a run. A
future OS/container worker needs a separate architecture, dependency/licence,
resource-limit, filesystem/network-isolation, and independent security review;
it cannot be silently introduced into v6.

No secret, personal data, source credential, or capital authority may be stored
in a v6 record, report, dashboard view, or test fixture. Existing redaction and
source-policy controls remain mandatory. A v6 report is engineering evidence,
not an investment recommendation or release claim.

## Incident and rollback

On a validation/lineage/PIT failure: stop the affected programme, retain its
attempted record when it was created, return a typed denial/abstention, and do
not invoke risk/execution/promotion code. On a discovered implementation defect:
freeze v6 acceptance, preserve the audit artefact, test the fix first, re-run
the full gate and independent audit, then revert only the isolated v6 commit if
needed. No path permits deleting or rewriting historical trial evidence.
