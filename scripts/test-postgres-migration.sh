#!/usr/bin/env bash
set -euo pipefail

DB="aegisquant_m0_test_${PPID}_$$"
ROLE_A="aegisquant_tenant_a_${PPID}_$$"
ROLE_B="aegisquant_tenant_b_${PPID}_$$"
cleanup() {
  psql -X -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS "$DB" WITH (FORCE);" >/dev/null 2>&1 || true
  psql -X -v ON_ERROR_STOP=1 -d postgres -c "DROP ROLE IF EXISTS "$ROLE_A";" >/dev/null 2>&1 || true
  psql -X -v ON_ERROR_STOP=1 -d postgres -c "DROP ROLE IF EXISTS "$ROLE_B";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for role in "$ROLE_A" "$ROLE_B"; do
  psql -X -v ON_ERROR_STOP=1 -d postgres -c     "CREATE ROLE "$role" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;" >/dev/null
done
psql -X -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE "$DB";" >/dev/null
psql -X -v ON_ERROR_STOP=1 -d "$DB"   -f infrastructure/postgres/migrations/0001_security_kernel.sql >/dev/null
psql -X -v ON_ERROR_STOP=1 -d "$DB"   -f infrastructure/postgres/migrations/0002_durable_offline_execution.sql >/dev/null

psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
INSERT INTO tenant_role_bindings (database_role, tenant_id)
VALUES ('$ROLE_A', 'tenant-a'), ('$ROLE_B', 'tenant-b');
GRANT USAGE ON SCHEMA public TO "$ROLE_A", "$ROLE_B";
GRANT SELECT, INSERT ON cases, case_events TO "$ROLE_A", "$ROLE_B";
GRANT UPDATE ON case_events TO "$ROLE_A", "$ROLE_B"; -- trigger must still reject
GRANT EXECUTE ON FUNCTION aq_current_tenant_id() TO "$ROLE_A", "$ROLE_B";
GRANT EXECUTE ON FUNCTION aq_record_idempotency(text,text,text,jsonb,text)
  TO "$ROLE_A", "$ROLE_B";
GRANT SELECT ON idempotency_records TO "$ROLE_A", "$ROLE_B";
GRANT EXECUTE ON FUNCTION aq_prepare_paper_account(text,uuid,text,bigint,text,jsonb)
  TO "$ROLE_A", "$ROLE_B";
GRANT EXECUTE ON FUNCTION aq_record_paper_execution(
  text,uuid,text,uuid,text,text,text,text,text,jsonb,bigint,text,jsonb
) TO "$ROLE_A", "$ROLE_B";
GRANT EXECUTE ON FUNCTION aq_record_execution_reconciliation(text,uuid,text,uuid,text)
  TO "$ROLE_A", "$ROLE_B";
GRANT SELECT, UPDATE ON paper_account_snapshots, consumed_risk_decisions, paper_execution_results
  TO "$ROLE_A", "$ROLE_B";
SQL

insert_case() {
  local role="$1" tenant="$2" case_id="$3"
  psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$role";
INSERT INTO cases (
  tenant_id, case_id, strategy_id, request, status, created_at, created_by, updated_at
) VALUES (
  '$tenant', '$case_id', 'control', '{}', 'CASE_CREATED', now(), 'test', now()
);
SQL
}
insert_case "$ROLE_A" tenant-a 00000000-0000-0000-0000-000000000001
insert_case "$ROLE_B" tenant-b 00000000-0000-0000-0000-000000000002

for spec in "$ROLE_A tenant-a 1" "$ROLE_B tenant-b 1"; do
  read -r role tenant expected <<<"$spec"
  visible=$(psql -X -At -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$role";
SELECT count(*) FROM cases;
SQL
)
  visible=$(printf '%s
' "$visible" | grep -E '^[0-9]+$' | tail -1)
  [[ "$visible" == "$expected" ]]
done

# A tenant-bound database identity cannot assert a different tenant.
if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
INSERT INTO cases (
  tenant_id, case_id, strategy_id, request, status, created_at, created_by, updated_at
) VALUES (
  'tenant-b', '00000000-0000-0000-0000-000000000003', 'control', '{}',
  'CASE_CREATED', now(), 'test', now()
);
SQL
then
  echo 'cross-tenant insert unexpectedly succeeded' >&2
  exit 1
fi

# The authenticated tenant role cannot assume the other tenant role.
if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SET ROLE "$ROLE_B";
SQL
then
  echo 'tenant role unexpectedly assumed another tenant role' >&2
  exit 1
fi

# DB trigger owns field-bound content, sequence/predecessor, and chain digests.
psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$ROLE_A";
INSERT INTO case_events (
  tenant_id, case_id, event_id, sequence, event_type, occurred_at, recorded_at,
  actor_id, correlation_id, idempotency_key, payload_canonical
) VALUES (
  'tenant-a', '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000010', 1, 'CASE_CREATED',
  TIMESTAMPTZ '2026-01-01T00:00:00Z', TIMESTAMPTZ '2026-01-01T00:00:00Z',
  'test', '00000000-0000-0000-0000-000000000011', 'event-1', '["object",[]]'
);
SQL

golden_values=$(psql -X -At -F '|' -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT event_content_digest, event_digest FROM case_events WHERE sequence = 1;
SQL
)
golden_values=$(printf '%s
' "$golden_values" | grep '^sha256:' | tail -1)
[[ "$golden_values" == "sha256:782684f277d1f4ebb76c152d18fa42fcc657a8a53d3d435eb49489723de4a158|sha256:46b856958022ff7f82ee1478ad6825a04f4f49971077aa856229a0365a82b374" ]]

# Caller-supplied fake preimages/digests are overwritten from the authoritative row.
psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$ROLE_B";
INSERT INTO case_events (
  tenant_id, case_id, event_id, sequence, event_type, occurred_at, recorded_at,
  actor_id, correlation_id, idempotency_key, payload_canonical,
  event_content_canonical, event_content_digest, event_digest
) VALUES (
  'tenant-b', '00000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000020', 1, 'DIFFERENT_EVENT',
  TIMESTAMPTZ '2026-01-01T00:00:00Z', TIMESTAMPTZ '2026-01-01T00:00:00Z',
  'test', '00000000-0000-0000-0000-000000000021', 'event-b',
  '["object",[["value",["string","B"]]]]', 'not-the-row',
  'sha256:29548ca88a5f6c54d511fd72bc9f12f3f4d2fcc6549d47bda7fa494a075e46d7',
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
);
SQL

different_digest=$(psql -X -At -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_B";
SELECT event_digest FROM case_events WHERE sequence = 1;
SQL
)
different_digest=$(printf '%s
' "$different_digest" | grep '^sha256:' | tail -1)
[[ "$different_digest" != "sha256:46b856958022ff7f82ee1478ad6825a04f4f49971077aa856229a0365a82b374" ]]

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
INSERT INTO case_events (
  tenant_id, case_id, event_id, sequence, event_type, occurred_at, recorded_at,
  actor_id, correlation_id, idempotency_key, payload_canonical, previous_event_digest
) VALUES (
  'tenant-a', '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000012', 9, 'BAD_CHAIN', now(), now(),
  'test', '00000000-0000-0000-0000-000000000013', 'event-9', '["object",[]]',
  'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
);
SQL
then
  echo 'arbitrary event chain unexpectedly succeeded' >&2
  exit 1
fi

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
UPDATE case_events SET payload_canonical = '["object",[["tampered",["boolean",true]]]]'
WHERE sequence = 1;
SQL
then
  echo 'append-only event mutation unexpectedly succeeded' >&2
  exit 1
fi

# Atomic idempotency helper returns the same record and rejects changed content.
psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_idempotency(
  'evidence.register', 'idem-1',
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  '{"evidence_id":"one"}', 'SUCCEEDED'
);
SELECT aq_record_idempotency(
  'evidence.register', 'idem-1',
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  '{"evidence_id":"one"}', 'SUCCEEDED'
);
SQL

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_idempotency(
  'evidence.register', 'idem-1',
  'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  '{"evidence_id":"two"}', 'SUCCEEDED'
);
SQL
then
  echo 'idempotency conflict unexpectedly succeeded' >&2
  exit 1
fi

# A durable account transition consumes one decision and records one result exactly once.
jsonb_golden=$(psql -X -At -v ON_ERROR_STOP=1 -d "$DB" \
  -c "SELECT aq_jsonb_digest('{\"aaaa\":1,\"b\":2,\"cc\":3}');")
[[ "$jsonb_golden" == "sha256:ea883663873df15b8f03c891f1cbc754fa22515473ac26d0ad4a32e741238841" ]]

psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_prepare_paper_account(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1', 0,
  'sha256:ef36b4df8d2068129dfb1e91543cd8ef1075a1fb3574ded2e1923733c6fa927b',
  '{"cash":"10000","positions":[]}'
);
SELECT aq_record_paper_execution(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000030', 'execute-1', '0123456789abcdef0123456789abcdef',
  'sha256:2222222222222222222222222222222222222222222222222222222222222222',
  'sha256:3333333333333333333333333333333333333333333333333333333333333333',
  'sha256:9d64379e8ea21a3cb726d7183f048fee15c4347d7911453f03a06c2af601bde8',
  '{"fills":[{"fill_id":"fill-1"}],"risk_decision_nonce":"0123456789abcdef0123456789abcdef","risk_decision_digest":"sha256:2222222222222222222222222222222222222222222222222222222222222222"}', 1,
  'sha256:b39282781415750ed7e03bd54492c42197c5fe57bad40ec2de9b1f8094536c66',
  '{"cash":"9900","positions":[{"instrument_id":"AAA","quantity":"1"}]}'
);
SELECT aq_record_paper_execution(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000030', 'execute-1', '0123456789abcdef0123456789abcdef',
  'sha256:2222222222222222222222222222222222222222222222222222222222222222',
  'sha256:3333333333333333333333333333333333333333333333333333333333333333',
  'sha256:9d64379e8ea21a3cb726d7183f048fee15c4347d7911453f03a06c2af601bde8',
  '{"fills":[{"fill_id":"fill-1"}],"risk_decision_nonce":"0123456789abcdef0123456789abcdef","risk_decision_digest":"sha256:2222222222222222222222222222222222222222222222222222222222222222"}', 1,
  'sha256:b39282781415750ed7e03bd54492c42197c5fe57bad40ec2de9b1f8094536c66',
  '{"cash":"9900","positions":[{"instrument_id":"AAA","quantity":"1"}]}'
);
SQL

durable_counts=$(psql -X -At -F '|' -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT
  (SELECT count(*) FROM consumed_risk_decisions),
  (SELECT count(*) FROM paper_execution_results),
  (SELECT jsonb_array_length(result_payload->'fills') FROM paper_execution_results),
  (SELECT count(*) FROM paper_account_snapshots);
SQL
)
durable_counts=$(printf '%s\n' "$durable_counts" | grep -E '^[0-9]+\|' | tail -1)
[[ "$durable_counts" == "1|1|1|2" ]]

pre_reconcile_count=$(psql -X -At -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT count(*) FROM case_events WHERE event_type = 'EXECUTION_RECONCILED';
SQL
)
pre_reconcile_count=$(printf '%s\n' "$pre_reconcile_count" | grep -E '^[0-9]+$' | tail -1)
[[ "$pre_reconcile_count" == "0" ]]

psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_execution_reconciliation(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000030',
  'sha256:9d64379e8ea21a3cb726d7183f048fee15c4347d7911453f03a06c2af601bde8'
);
SELECT aq_record_execution_reconciliation(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000030',
  'sha256:9d64379e8ea21a3cb726d7183f048fee15c4347d7911453f03a06c2af601bde8'
);
SQL

durable_event_counts=$(psql -X -At -F '|' -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT
  count(*) FILTER (WHERE event_type = 'DURABLE_CASE_PREPARED'),
  count(*) FILTER (WHERE event_type = 'PAPER_EXECUTION_RECORDED'),
  count(*) FILTER (WHERE event_type = 'EXECUTION_RECONCILED')
FROM case_events
WHERE case_id = '00000000-0000-0000-0000-000000000001';
SQL
)
durable_event_counts=$(printf '%s\n' "$durable_event_counts" | grep -E '^[0-9]+\|' | tail -1)
[[ "$durable_event_counts" == "1|1|1" ]]

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_execution_reconciliation(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000030',
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
);
SQL
then
  echo 'reconciliation of a different result unexpectedly succeeded' >&2
  exit 1
fi

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_paper_execution(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000032', 'execute-unbound',
  'abcdef0123456789abcdef0123456789',
  'sha256:2222222222222222222222222222222222222222222222222222222222222222',
  'sha256:3333333333333333333333333333333333333333333333333333333333333333',
  'sha256:8640f5d3bf460c53c00a28b5bc917af02b6b1f6abb973d8cb884b7566697774b',
  '{"fills":[],"risk_decision_nonce":"abcdef0123456789abcdef0123456789","risk_decision_digest":"sha256:4444444444444444444444444444444444444444444444444444444444444444"}', 2,
  'sha256:4be01a978d923e44cc14effe36e384e528aaf2ce266b6addeed6e023faececc4',
  '{"cash":"9900","positions":[]}'
);
SQL
then
  echo 'execution result with an unbound risk decision unexpectedly succeeded' >&2
  exit 1
fi

# Preparation also creates an absent case instead of requiring an out-of-band insert.
psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_prepare_paper_account(
  'tenant-a', '00000000-0000-0000-0000-000000000004', 'paper-new', 0,
  'sha256:ef36b4df8d2068129dfb1e91543cd8ef1075a1fb3574ded2e1923733c6fa927b',
  '{"cash":"10000","positions":[]}'
);
SQL

prepared_case_counts=$(psql -X -At -F '|' -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT
  (SELECT count(*) FROM cases
   WHERE case_id = '00000000-0000-0000-0000-000000000004'),
  (SELECT count(*) FROM case_events
   WHERE case_id = '00000000-0000-0000-0000-000000000004'
     AND event_type = 'DURABLE_CASE_PREPARED');
SQL
)
prepared_case_counts=$(printf '%s\n' "$prepared_case_counts" | grep -E '^[0-9]+\|' | tail -1)
[[ "$prepared_case_counts" == "1|1" ]]

tenant_b_visible=$(psql -X -At -v ON_ERROR_STOP=1 -d "$DB" <<SQL
SET SESSION AUTHORIZATION "$ROLE_B";
SELECT count(*) FROM paper_execution_results;
SQL
)
tenant_b_visible=$(printf '%s\n' "$tenant_b_visible" | grep -E '^[0-9]+$' | tail -1)
[[ "$tenant_b_visible" == "0" ]]

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_prepare_paper_account(
  'tenant-b', '00000000-0000-0000-0000-000000000001', 'paper-x', 0,
  'sha256:ef36b4df8d2068129dfb1e91543cd8ef1075a1fb3574ded2e1923733c6fa927b',
  '{"cash":"10000","positions":[]}'
);
SQL
then
  echo 'payload tenant unexpectedly replaced the authenticated database tenant' >&2
  exit 1
fi

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
UPDATE paper_account_snapshots SET snapshot_payload = '{}' WHERE state_sequence = 1;
SQL
then
  echo 'durable account snapshot mutation unexpectedly succeeded' >&2
  exit 1
fi

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_prepare_paper_account(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1', 0,
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  '{"cash":"1","positions":[]}'
);
SQL
then
  echo 'changed paper account preparation unexpectedly succeeded' >&2
  exit 1
fi

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_paper_execution(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000031', 'execute-2', '0123456789abcdef0123456789abcdef',
  'sha256:2222222222222222222222222222222222222222222222222222222222222222',
  'sha256:6666666666666666666666666666666666666666666666666666666666666666',
  'sha256:f3e5a8ffa84ebd8849e9625be3a17bd8859cbb36aa1b8b36fbeb78a69f2a2561',
  '{"fills":[],"risk_decision_nonce":"0123456789abcdef0123456789abcdef","risk_decision_digest":"sha256:2222222222222222222222222222222222222222222222222222222222222222"}', 2,
  'sha256:4be01a978d923e44cc14effe36e384e528aaf2ce266b6addeed6e023faececc4',
  '{"cash":"9900","positions":[]}'
);
SQL
then
  echo 'risk decision nonce reuse unexpectedly succeeded' >&2
  exit 1
fi

if psql -X -v ON_ERROR_STOP=1 -d "$DB" <<SQL >/dev/null 2>&1
SET SESSION AUTHORIZATION "$ROLE_A";
SELECT aq_record_paper_execution(
  'tenant-a', '00000000-0000-0000-0000-000000000001', 'paper-1',
  '00000000-0000-0000-0000-000000000030', 'execute-1', '0123456789abcdef0123456789abcdef',
  'sha256:2222222222222222222222222222222222222222222222222222222222222222',
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  'sha256:9d64379e8ea21a3cb726d7183f048fee15c4347d7911453f03a06c2af601bde8',
  '{"fills":[{"fill_id":"fill-1"}],"risk_decision_nonce":"0123456789abcdef0123456789abcdef","risk_decision_digest":"sha256:2222222222222222222222222222222222222222222222222222222222222222"}', 1,
  'sha256:b39282781415750ed7e03bd54492c42197c5fe57bad40ec2de9b1f8094536c66',
  '{"cash":"9900","positions":[{"instrument_id":"AAA","quantity":"1"}]}'
);
SQL
then
  echo 'durable execution idempotency conflict unexpectedly succeeded' >&2
  exit 1
fi

echo 'PostgreSQL migration, bound-tenant RLS, DB-owned chain, idempotency, and append-only checks passed.'
