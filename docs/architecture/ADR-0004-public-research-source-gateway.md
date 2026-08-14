# ADR-0004: Public research source gateway

## Decision

Last30Days and Scrapling are runtime research adapters only behind the
capability-gated `SourceGateway`. They are not workflow dependencies, evidence
authorities, or execution inputs. The operator-approved M2 implementation
adds a recorded-only `Last30DaysResearchRecord`: it binds a gateway receipt,
its content digest, tenant, case, snapshot, manifest, and availability time.

Every request requires a tenant/case-bound grant, exact tool ID, data scope,
exact destination hostname, call/cost budget, HTTPS URL, and a public endpoint.
Cookies, custom headers, proxy credentials, browser profiles, non-default
ports, wildcard domains, and cross-host redirects are prohibited. Retrieved
content remains untrusted and needs a rights/provenance record before it may
enter an evidence artifact.

## Consequences

The in-process boundary uses an injected transport; production activation needs
an egress proxy that resolves DNS and blocks non-public destinations. The
repository does not execute the installed Last30Days or Scrapling binaries
directly, because those tools can reach destinations outside a case grant. A
future worker adapter must preserve this gateway check before each egress.

The recorded adapter has no network capability and retains no response body.
It rejects a non-Last30Days receipt or a body whose digest differs from the
receipt. A separately verified proxy must enforce robots and rights policy,
DNS/public-address checks, exact tenant/case hostname grants, quotas, and
no redirects before live source capture can be enabled.
