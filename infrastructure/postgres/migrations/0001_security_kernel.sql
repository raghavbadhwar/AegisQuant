-- AegisQuant M0 security-kernel schema (PostgreSQL 16)
-- Run as a migration owner distinct from the non-owner application role.

BEGIN;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenant_role_bindings (
    database_role name PRIMARY KEY,
    tenant_id text NOT NULL
);
REVOKE ALL ON tenant_role_bindings FROM PUBLIC;

CREATE FUNCTION aq_current_tenant_id() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT tenant_id FROM public.tenant_role_bindings WHERE database_role = session_user
$$;
REVOKE ALL ON FUNCTION aq_current_tenant_id() FROM PUBLIC;

CREATE FUNCTION aq_frame(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT
AS $$
    SELECT octet_length(convert_to(value, 'UTF8'))::text || ':' || value
$$;
REVOKE ALL ON FUNCTION aq_frame(text) FROM PUBLIC;

CREATE FUNCTION aq_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table % does not permit %', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE FUNCTION aq_enforce_case_event_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    prior_sequence bigint;
    prior_digest text;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id || ':' || NEW.case_id::text, 0)
    );
    SELECT sequence, event_digest INTO prior_sequence, prior_digest
    FROM case_events
    WHERE tenant_id = NEW.tenant_id AND case_id = NEW.case_id
    ORDER BY sequence DESC
    LIMIT 1;

    IF NOT FOUND THEN
        IF NEW.sequence <> 1 OR NEW.previous_event_digest IS NOT NULL THEN
            RAISE EXCEPTION 'first case event must have sequence 1 and no predecessor';
        END IF;
    ELSIF NEW.sequence <> prior_sequence + 1 OR NEW.previous_event_digest <> prior_digest THEN
        RAISE EXCEPTION 'case event sequence or predecessor does not extend the current chain';
    END IF;

    NEW.event_content_canonical := 'AEGISQUANT_CASE_EVENT_CONTENT_V1'
        || aq_frame(NEW.schema_version::text)
        || aq_frame(NEW.tenant_id)
        || aq_frame(NEW.case_id::text)
        || aq_frame(NEW.event_id::text)
        || aq_frame(NEW.sequence::text)
        || aq_frame(NEW.event_type)
        || aq_frame(to_char(
            NEW.occurred_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ))
        || aq_frame(to_char(
            NEW.recorded_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ))
        || aq_frame(NEW.actor_id)
        || aq_frame(NEW.correlation_id::text)
        || aq_frame(coalesce(NEW.causation_id::text, '<NULL>'))
        || aq_frame(NEW.idempotency_key)
        || aq_frame(NEW.payload_canonical);
    NEW.event_content_digest := 'sha256:' || encode(
        digest(convert_to(NEW.event_content_canonical, 'UTF8'), 'sha256'), 'hex'
    );
    NEW.event_digest := 'sha256:' || encode(
        digest(
            convert_to(
                'AEGISQUANT_CASE_EVENT_CHAIN_V1|'
                || coalesce(NEW.previous_event_digest, 'ROOT')
                || '|' || NEW.event_content_digest,
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    );
    RETURN NEW;
END;
$$;

CREATE TABLE cases (
    tenant_id text NOT NULL,
    case_id uuid NOT NULL,
    strategy_id text NOT NULL,
    request jsonb NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    created_by text NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, case_id)
);

CREATE TABLE case_events (
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    tenant_id text NOT NULL,
    case_id uuid NOT NULL,
    event_id uuid NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    actor_id text NOT NULL,
    correlation_id uuid NOT NULL,
    causation_id uuid,
    idempotency_key text NOT NULL,
    payload_canonical text NOT NULL,
    event_content_canonical text NOT NULL,
    event_content_digest text NOT NULL,
    previous_event_digest text,
    event_digest text NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    UNIQUE (tenant_id, case_id, sequence),
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    CHECK (event_content_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (event_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (previous_event_digest IS NULL OR previous_event_digest ~ '^sha256:[0-9a-f]{64}$')
);
CREATE TRIGGER case_events_enforce_chain
BEFORE INSERT ON case_events
FOR EACH ROW EXECUTE FUNCTION aq_enforce_case_event_chain();

CREATE TABLE idempotency_records (
    tenant_id text NOT NULL,
    operation_type text NOT NULL,
    idempotency_key text NOT NULL,
    request_digest text NOT NULL,
    result_reference jsonb,
    outcome text NOT NULL CHECK (outcome IN ('SUCCEEDED', 'FAILED', 'UNCERTAIN')),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, operation_type, idempotency_key),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE FUNCTION aq_record_idempotency(
    p_operation_type text,
    p_idempotency_key text,
    p_request_digest text,
    p_result_reference jsonb,
    p_outcome text
) RETURNS idempotency_records
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    tenant text := aq_current_tenant_id();
    stored idempotency_records;
BEGIN
    IF tenant IS NULL THEN
        RAISE EXCEPTION 'database role is not bound to a tenant';
    END IF;
    INSERT INTO idempotency_records (
        tenant_id, operation_type, idempotency_key, request_digest,
        result_reference, outcome, created_at
    ) VALUES (
        tenant, p_operation_type, p_idempotency_key, p_request_digest,
        p_result_reference, p_outcome, clock_timestamp()
    ) ON CONFLICT DO NOTHING;

    SELECT * INTO stored FROM idempotency_records
    WHERE tenant_id = tenant
      AND operation_type = p_operation_type
      AND idempotency_key = p_idempotency_key;
    IF stored.request_digest <> p_request_digest THEN
        RAISE EXCEPTION 'idempotency key reused with a different request digest';
    END IF;
    RETURN stored;
END;
$$;
REVOKE ALL ON FUNCTION aq_record_idempotency(text,text,text,jsonb,text) FROM PUBLIC;

CREATE TABLE object_manifests (
    tenant_id text NOT NULL,
    object_id uuid NOT NULL,
    bucket text NOT NULL,
    object_key text NOT NULL,
    object_version text NOT NULL,
    content_digest text NOT NULL,
    capture_metadata_digest text,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL,
    retention_class text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, content_digest),
    CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (capture_metadata_digest IS NULL OR capture_metadata_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE evidence_records (
    tenant_id text NOT NULL,
    evidence_id uuid NOT NULL,
    logical_document_id uuid NOT NULL,
    revision_number integer NOT NULL CHECK (revision_number > 0),
    supersedes_evidence_id uuid,
    source_type text NOT NULL,
    document_type text NOT NULL,
    entity_ids text[] NOT NULL,
    event_time timestamptz,
    published_at timestamptz,
    first_observed_at timestamptz NOT NULL,
    available_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL,
    revised_at timestamptz,
    valid_from timestamptz,
    valid_to timestamptz,
    withdrawn_at timestamptz,
    object_id uuid NOT NULL,
    extractor_version text NOT NULL,
    parser_version text NOT NULL,
    rights_manifest_id text NOT NULL,
    source_quality numeric NOT NULL CHECK (source_quality BETWEEN 0 AND 1),
    extraction_confidence numeric NOT NULL CHECK (extraction_confidence BETWEEN 0 AND 1),
    historical_safe boolean NOT NULL,
    prompt_injection_flags text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, evidence_id),
    UNIQUE (tenant_id, logical_document_id, revision_number),
    FOREIGN KEY (tenant_id, object_id) REFERENCES object_manifests (tenant_id, object_id),
    FOREIGN KEY (tenant_id, supersedes_evidence_id)
        REFERENCES evidence_records (tenant_id, evidence_id),
    CHECK (available_at >= first_observed_at),
    CHECK (ingested_at >= first_observed_at),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
    CHECK (withdrawn_at IS NULL OR withdrawn_at >= available_at)
);

CREATE TABLE artifact_envelopes (
    tenant_id text NOT NULL,
    artifact_id uuid NOT NULL,
    case_id uuid NOT NULL,
    schema_id text NOT NULL,
    schema_version text NOT NULL,
    object_id uuid NOT NULL,
    payload_digest text NOT NULL,
    producer_stamp jsonb NOT NULL,
    data_snapshot_id text NOT NULL,
    parent_artifact_ids uuid[] NOT NULL DEFAULT '{}',
    evidence_ids uuid[] NOT NULL DEFAULT '{}',
    classification text NOT NULL,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, artifact_id),
    UNIQUE (tenant_id, case_id, idempotency_key),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    FOREIGN KEY (tenant_id, object_id) REFERENCES object_manifests (tenant_id, object_id),
    CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE validation_receipts (
    tenant_id text NOT NULL,
    receipt_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    artifact_digest text NOT NULL,
    validator_id text NOT NULL,
    validator_version text NOT NULL,
    policy_id text NOT NULL,
    checks jsonb NOT NULL,
    accepted boolean NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, receipt_id),
    FOREIGN KEY (tenant_id, artifact_id) REFERENCES artifact_envelopes (tenant_id, artifact_id),
    CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE capability_grants (
    tenant_id text NOT NULL,
    grant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    agent_id text NOT NULL,
    grant_digest text NOT NULL,
    grant_payload jsonb NOT NULL,
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, grant_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    CHECK (expires_at > issued_at),
    CHECK (grant_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE capability_revocations (
    tenant_id text NOT NULL,
    revocation_id uuid NOT NULL,
    grant_id uuid NOT NULL,
    reason_code text NOT NULL,
    revoked_at timestamptz NOT NULL,
    revoked_by text NOT NULL,
    PRIMARY KEY (tenant_id, revocation_id),
    UNIQUE (tenant_id, grant_id),
    FOREIGN KEY (tenant_id, grant_id) REFERENCES capability_grants (tenant_id, grant_id)
);

CREATE TABLE outbox_events (
    tenant_id text NOT NULL,
    outbox_event_id uuid NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL,
    event_type text NOT NULL,
    payload_reference jsonb NOT NULL,
    payload_digest text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, outbox_event_id),
    CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE outbox_delivery_attempts (
    tenant_id text NOT NULL,
    attempt_id uuid NOT NULL,
    outbox_event_id uuid NOT NULL,
    worker_id text NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    outcome text NOT NULL CHECK (outcome IN ('SUCCEEDED', 'FAILED', 'UNCERTAIN')),
    attempted_at timestamptz NOT NULL,
    detail_digest text,
    PRIMARY KEY (tenant_id, attempt_id),
    UNIQUE (tenant_id, outbox_event_id, attempt_number),
    FOREIGN KEY (tenant_id, outbox_event_id)
        REFERENCES outbox_events (tenant_id, outbox_event_id),
    CHECK (detail_digest IS NULL OR detail_digest ~ '^sha256:[0-9a-f]{64}$')
);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'case_events', 'idempotency_records', 'object_manifests', 'evidence_records',
        'artifact_envelopes', 'validation_receipts', 'capability_grants',
        'capability_revocations', 'outbox_events', 'outbox_delivery_attempts'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_reject_mutation BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION aq_reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END;
$$;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'cases', 'case_events', 'idempotency_records', 'object_manifests',
        'evidence_records', 'artifact_envelopes', 'validation_receipts',
        'capability_grants', 'capability_revocations', 'outbox_events',
        'outbox_delivery_attempts'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY %I_tenant_isolation ON %I USING '
            '(tenant_id = aq_current_tenant_id()) '
            'WITH CHECK (tenant_id = aq_current_tenant_id())',
            table_name, table_name
        );
    END LOOP;
END;
$$;

REVOKE UPDATE, DELETE, TRUNCATE ON
    case_events, idempotency_records, object_manifests, evidence_records,
    artifact_envelopes, validation_receipts, capability_grants,
    capability_revocations, outbox_events, outbox_delivery_attempts
FROM PUBLIC;

COMMIT;
