# ADR-0002: Keep interfaces stable; re-evaluate named infrastructure

- **Status:** Accepted for development; production choice pending benchmarks and legal review
- **Date:** 2026-08-08

## Decisions

1. Keep an S3-compatible immutable object-store interface, not a MinIO-specific contract. The MinIO community repository is currently archived/unmaintained and AGPL-3.0; legacy binaries do not receive updates. Development starts with a local immutable backend. AWS S3, SeaweedFS, RustFS, or a managed equivalent must pass WORM, security, durability, license, restore, and operational tests before selection.
2. Keep a Redis-protocol transient-cache interface. Prefer Valkey for new self-hosted deployments because it is BSD-3-Clause and Linux Foundation governed; Redis 8 is tri-licensed under RSALv2/SSPLv1/AGPLv3. No authoritative state may depend on this cache.
3. LiteLLM remains a candidate gateway, but OSS versus enterprise feature boundaries and admin-plane isolation must be captured before production use.
4. GBrain is an optional derived research projection. Its rapid release cadence and young codebase require a pinned adapter and export/rebuild path; it never owns financial truth.
5. NautilusTrader is LGPL-3.0. Use as a separately versioned adapter/service and complete license/distribution review before any packaged deployment.
