# ADR-0003: Personal local-first deployment boundary

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

AegisQuant OS is for one person's local use. It is not a hosted SaaS, shared enterprise platform, or public service. Reliability and financial safety remain important, but enterprise-distributed infrastructure would add failure modes and operating cost without serving the intended deployment.

## Decision

1. Ship as one local monorepo and one documented local runtime profile.
2. Prefer a single local PostgreSQL instance, a local Temporal development/runtime service, local filesystem content-addressed storage, and local model services.
3. Keep logical `tenant_id` scoping in authoritative contracts and storage. It provides defense in depth, test isolation, and a clean boundary between personal portfolios or experiments; it does not imply a multi-customer control plane.
4. Do not require Kubernetes, service mesh, multi-region failover, cloud IAM, managed queues, public ingress, or continuous hosted services for the supported personal profile.
5. Replace enterprise availability claims with local recovery controls: deterministic replay, transactional idempotency, encrypted backups, restore drills, integrity verification, least-privilege local processes, and explicit operator confirmation.
6. Default all network-capable integrations off. No broker adapter, live-order path, unrestricted web ingestion, remote model provider, or telemetry export is enabled by installation.
7. Treat the local OS account as the human operator, while still keeping model and tool processes away from signing keys, database-owner credentials, and any future broker secret.

## Consequences

- Installation and operation remain understandable on one workstation.
- The project retains production-oriented correctness without pretending to offer enterprise availability.
- Tests may use embedded/local services; Docker and cloud accounts are optional rather than baseline requirements.
- A future shared or hosted edition would require a new ADR and a separate threat model rather than silently expanding this profile.
