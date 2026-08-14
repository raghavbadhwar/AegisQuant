# ADR-0004: Recorded public-research captures; runtime gateway deferred

## Decision

M0 contains no callable Last30Days, Scrapling, HTTP transport, or public-source
gateway. It accepts only recorded `SourceReceipt` and body fixtures whose digest,
tenant, case, snapshot, manifest, and availability time are validated before a
`Last30DaysResearchRecord` is created.

## Consequences

The recorded adapter has no network capability and retains no response body.
It rejects a non-Last30Days receipt or a body whose digest differs from the
receipt. A separately verified proxy must enforce robots and rights policy,
DNS/public-address checks, exact tenant/case hostname grants, quotas, and
no redirects before live source capture can be enabled.

Any future runtime gateway requires a new milestone, ADR revision, explicit
operator approval, and adversarial capability/network tests; this record does
not authorize or implement it.
