# Design validation — 2026-08-08

## Overall decision

Proceed with a **controlled build**, not a production or live-trading release. The four-service boundary, deterministic hard risk, typed artifacts, PIT evidence, single Temporal owner, and governed learning loop are retained. Security M0 precedes the original foundation phase.

## Material validated changes

- Current PydanticAI documentation uses `TemporalDurability`; legacy `TemporalAgent` is scheduled for removal in v3. Model requests and I/O tool calls execute as activities, while deterministic coordination replays in the workflow.
- Temporal Python's sandbox reduces but does not eliminate nondeterminism. Worker versioning and replay tests are required.
- Current MinIO community source is archived/unmaintained and AGPL-3.0; do not make MinIO a hard dependency.
- Redis 8 is tri-licensed; use a cache interface and prefer Valkey in self-hosted development.
- GBrain, Agent Reach, and Scrapling are adapter candidates, not trusted control planes. Agent Reach runtime auto-install is prohibited; Scrapling robots compliance is opt-in and therefore must be forced by policy.
- NautilusTrader currently documents startup and continuous execution reconciliation, but live trading remains excluded. Its LGPL-3.0 license requires distribution review.
- LiteLLM's repository separates MIT-licensed OSS code from commercially licensed enterprise code; required gateway controls must be mapped to the correct edition.

## Independent financial guidance

The first quant workflow is a pipeline/control experiment, not an alpha product: one daily US ETF plus cash, a pre-registered deterministic monthly signal, next-session eligibility, immutable trial accounting, corporate-action/cash reconciliation, deterministic baselines, PIT checks, and forward paper observation. Behavioral/graph features and portfolio optimization are excluded initially.

## Primary sources

- PydanticAI Temporal: https://pydantic.dev/docs/ai/integrations/durable_execution/temporal/
- Temporal Python sandbox: https://docs.temporal.io/develop/python/best-practices/python-sdk-sandbox
- Temporal workflow versioning: https://docs.temporal.io/develop/python/workflows/versioning
- PostgreSQL row security: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- MinIO repository: https://github.com/minio/minio
- Redis licensing: https://redis.io/legal/licenses/
- Valkey: https://valkey.io/
- LiteLLM licensing/docs: https://github.com/BerriAI/litellm and https://docs.litellm.ai/
- Scrapling docs: https://scrapling.readthedocs.io/en/latest/
- NautilusTrader live/reconciliation: https://nautilustrader.io/docs/latest/concepts/live/
- OWASP LLM01/LLM06: https://genai.owasp.org/
- NIST SP 800-218A: https://csrc.nist.gov/pubs/sp/800/218/a/final

All web snippets were used as discovery leads; material decisions were checked against linked project/official documentation or repository metadata.
