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

echo 'PostgreSQL migration, bound-tenant RLS, DB-owned chain, idempotency, and append-only checks passed.'
