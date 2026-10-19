-- Durable, tenant-bound paper-account execution state.

BEGIN;

CREATE FUNCTION aq_jsonb_digest(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT
AS $$
    SELECT 'sha256:' || encode(
        digest(convert_to(value::text, 'UTF8'), 'sha256'),
        'hex'
    )
$$;
REVOKE ALL ON FUNCTION aq_jsonb_digest(jsonb) FROM PUBLIC;

CREATE TABLE paper_account_snapshots (
    tenant_id text NOT NULL,
    case_id uuid NOT NULL,
    account_id text NOT NULL,
    state_sequence bigint NOT NULL CHECK (state_sequence >= 0),
    snapshot_digest text NOT NULL,
    snapshot_payload jsonb NOT NULL,
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, account_id, state_sequence),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    CHECK (snapshot_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE consumed_risk_decisions (
    tenant_id text NOT NULL,
    case_id uuid NOT NULL,
    account_id text NOT NULL,
    nonce text NOT NULL,
    execution_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    decision_digest text NOT NULL,
    consumed_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, account_id, nonce),
    UNIQUE (tenant_id, execution_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    CHECK (nonce ~ '^[0-9a-f]{32,128}$'),
    CHECK (decision_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE paper_execution_results (
    tenant_id text NOT NULL,
    case_id uuid NOT NULL,
    account_id text NOT NULL,
    execution_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    nonce text NOT NULL,
    decision_digest text NOT NULL,
    request_digest text NOT NULL,
    result_digest text NOT NULL,
    result_payload jsonb NOT NULL,
    account_state_sequence bigint NOT NULL CHECK (account_state_sequence > 0),
    account_snapshot_digest text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, execution_id),
    UNIQUE (tenant_id, account_id, idempotency_key),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases (tenant_id, case_id),
    FOREIGN KEY (tenant_id, account_id, nonce)
        REFERENCES consumed_risk_decisions (tenant_id, account_id, nonce),
    FOREIGN KEY (tenant_id, account_id, account_state_sequence)
        REFERENCES paper_account_snapshots (tenant_id, account_id, state_sequence),
    CHECK (decision_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (result_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (account_snapshot_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE FUNCTION aq_append_durable_case_event(
    p_tenant_id text,
    p_case_id uuid,
    p_event_type text,
    p_idempotency_key text,
    p_payload_canonical text
) RETURNS case_events
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    tenant text := aq_current_tenant_id();
    prior_sequence bigint;
    prior_digest text;
    event_time timestamptz := clock_timestamp();
    stored case_events;
BEGIN
    IF tenant IS NULL OR p_tenant_id <> tenant THEN
        RAISE EXCEPTION 'event tenant does not match authenticated database tenant'
            USING ERRCODE = 'AQ004';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(tenant || ':' || p_case_id::text, 0));
    SELECT * INTO stored FROM case_events
    WHERE tenant_id = tenant AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF stored.case_id <> p_case_id
           OR stored.event_type <> p_event_type
           OR stored.payload_canonical <> p_payload_canonical THEN
            RAISE EXCEPTION 'durable event idempotency key reused with different content'
                USING ERRCODE = 'AQ001';
        END IF;
        RETURN stored;
    END IF;
    SELECT sequence, event_digest INTO prior_sequence, prior_digest
    FROM case_events
    WHERE tenant_id = tenant AND case_id = p_case_id
    ORDER BY sequence DESC
    LIMIT 1;
    INSERT INTO case_events (
        tenant_id, case_id, event_id, sequence, event_type, occurred_at, recorded_at,
        actor_id, correlation_id, idempotency_key, payload_canonical, previous_event_digest
    ) VALUES (
        tenant, p_case_id, gen_random_uuid(), coalesce(prior_sequence, 0) + 1,
        p_event_type, event_time, event_time, 'durable-offline-runner', p_case_id,
        p_idempotency_key, p_payload_canonical, prior_digest
    ) RETURNING * INTO stored;
    RETURN stored;
END;
$$;
REVOKE ALL ON FUNCTION aq_append_durable_case_event(text,uuid,text,text,text) FROM PUBLIC;

CREATE FUNCTION aq_prepare_paper_account(
    p_tenant_id text,
    p_case_id uuid,
    p_account_id text,
    p_state_sequence bigint,
    p_snapshot_digest text,
    p_snapshot_payload jsonb
) RETURNS paper_account_snapshots
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    tenant text := aq_current_tenant_id();
    stored paper_account_snapshots;
BEGIN
    IF tenant IS NULL THEN
        RAISE EXCEPTION 'database role is not bound to a tenant';
    END IF;
    IF p_tenant_id <> tenant THEN
        RAISE EXCEPTION 'payload tenant does not match authenticated database tenant'
            USING ERRCODE = 'AQ004';
    END IF;
    IF p_state_sequence <> 0 THEN
        RAISE EXCEPTION 'prepared paper account must start at state sequence 0';
    END IF;
    IF aq_jsonb_digest(p_snapshot_payload) <> p_snapshot_digest THEN
        RAISE EXCEPTION 'paper account snapshot digest does not bind its JSON payload'
            USING ERRCODE = 'AQ005';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(tenant || ':' || p_account_id, 0));
    SELECT * INTO stored FROM paper_account_snapshots
    WHERE tenant_id = tenant
      AND account_id = p_account_id
      AND state_sequence = p_state_sequence;
    IF FOUND THEN
        IF stored.case_id <> p_case_id
           OR stored.snapshot_digest <> p_snapshot_digest
           OR stored.snapshot_payload <> p_snapshot_payload THEN
            RAISE EXCEPTION 'paper account preparation key reused with different content'
                USING ERRCODE = 'AQ001';
        END IF;
        RETURN stored;
    END IF;
    INSERT INTO cases (
        tenant_id, case_id, strategy_id, request, status,
        created_at, created_by, updated_at
    ) VALUES (
        tenant, p_case_id, 'durable-offline-fixture',
        jsonb_build_object(
            'account_id', p_account_id,
            'initial_snapshot_digest', p_snapshot_digest
        ),
        'DURABLE_PREPARED', clock_timestamp(), 'durable-offline-runner', clock_timestamp()
    ) ON CONFLICT DO NOTHING;
    INSERT INTO paper_account_snapshots (
        tenant_id, case_id, account_id, state_sequence,
        snapshot_digest, snapshot_payload, recorded_at
    ) VALUES (
        tenant, p_case_id, p_account_id, p_state_sequence,
        p_snapshot_digest, p_snapshot_payload, clock_timestamp()
    ) RETURNING * INTO stored;
    PERFORM aq_append_durable_case_event(
        tenant,
        p_case_id,
        'DURABLE_CASE_PREPARED',
        'durable-prepare:' || p_account_id,
        '["object",[["account_id",["string","' || p_account_id
            || '"]],["snapshot_digest",["string","' || p_snapshot_digest || '"]]]]'
    );
    RETURN stored;
END;
$$;
REVOKE ALL ON FUNCTION aq_prepare_paper_account(text,uuid,text,bigint,text,jsonb) FROM PUBLIC;

CREATE FUNCTION aq_record_paper_execution(
    p_tenant_id text,
    p_case_id uuid,
    p_account_id text,
    p_execution_id uuid,
    p_idempotency_key text,
    p_nonce text,
    p_decision_digest text,
    p_request_digest text,
    p_result_digest text,
    p_result_payload jsonb,
    p_account_state_sequence bigint,
    p_account_snapshot_digest text,
    p_account_snapshot_payload jsonb
) RETURNS paper_execution_results
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    tenant text := aq_current_tenant_id();
    current_snapshot paper_account_snapshots;
    stored paper_execution_results;
BEGIN
    IF tenant IS NULL THEN
        RAISE EXCEPTION 'database role is not bound to a tenant';
    END IF;
    IF p_tenant_id <> tenant THEN
        RAISE EXCEPTION 'payload tenant does not match authenticated database tenant'
            USING ERRCODE = 'AQ004';
    END IF;
    IF aq_jsonb_digest(p_result_payload) <> p_result_digest
       OR aq_jsonb_digest(p_account_snapshot_payload) <> p_account_snapshot_digest THEN
        RAISE EXCEPTION 'execution digest does not bind its JSON payload'
            USING ERRCODE = 'AQ005';
    END IF;
    IF p_result_payload->>'risk_decision_nonce' IS DISTINCT FROM p_nonce
       OR p_result_payload->>'risk_decision_digest' IS DISTINCT FROM p_decision_digest THEN
        RAISE EXCEPTION 'execution result does not bind its consumed risk decision'
            USING ERRCODE = 'AQ005';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(tenant || ':' || p_account_id, 0));
    SELECT * INTO stored FROM paper_execution_results
    WHERE tenant_id = tenant
      AND account_id = p_account_id
      AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF stored.case_id <> p_case_id
           OR stored.execution_id <> p_execution_id
           OR stored.nonce <> p_nonce
           OR stored.decision_digest <> p_decision_digest
           OR stored.request_digest <> p_request_digest
           OR stored.result_digest <> p_result_digest
           OR stored.result_payload <> p_result_payload
           OR stored.account_state_sequence <> p_account_state_sequence
           OR stored.account_snapshot_digest <> p_account_snapshot_digest
           OR NOT EXISTS (
               SELECT 1 FROM paper_account_snapshots AS snapshot
               WHERE snapshot.tenant_id = tenant
                 AND snapshot.account_id = p_account_id
                 AND snapshot.state_sequence = p_account_state_sequence
                 AND snapshot.snapshot_payload = p_account_snapshot_payload
           ) THEN
            RAISE EXCEPTION 'durable execution idempotency key reused with different content'
                USING ERRCODE = 'AQ001';
        END IF;
        RETURN stored;
    END IF;

    SELECT * INTO current_snapshot FROM paper_account_snapshots
    WHERE tenant_id = tenant AND account_id = p_account_id
    ORDER BY state_sequence DESC
    LIMIT 1;
    IF NOT FOUND
       OR current_snapshot.case_id <> p_case_id
       OR current_snapshot.state_sequence + 1 <> p_account_state_sequence THEN
        RAISE EXCEPTION 'paper account state transition is not the next bound sequence'
            USING ERRCODE = 'AQ003';
    END IF;

    BEGIN
        INSERT INTO consumed_risk_decisions (
            tenant_id, case_id, account_id, nonce, execution_id,
            idempotency_key, decision_digest, consumed_at
        ) VALUES (
            tenant, p_case_id, p_account_id, p_nonce, p_execution_id,
            p_idempotency_key, p_decision_digest, clock_timestamp()
        );
    EXCEPTION WHEN unique_violation THEN
        RAISE EXCEPTION 'risk decision nonce or execution id was already consumed'
            USING ERRCODE = 'AQ002';
    END;

    INSERT INTO paper_account_snapshots (
        tenant_id, case_id, account_id, state_sequence,
        snapshot_digest, snapshot_payload, recorded_at
    ) VALUES (
        tenant, p_case_id, p_account_id, p_account_state_sequence,
        p_account_snapshot_digest, p_account_snapshot_payload, clock_timestamp()
    );
    INSERT INTO paper_execution_results (
        tenant_id, case_id, account_id, execution_id, idempotency_key, nonce,
        decision_digest, request_digest, result_digest, result_payload,
        account_state_sequence, account_snapshot_digest, created_at
    ) VALUES (
        tenant, p_case_id, p_account_id, p_execution_id, p_idempotency_key, p_nonce,
        p_decision_digest, p_request_digest, p_result_digest, p_result_payload,
        p_account_state_sequence, p_account_snapshot_digest, clock_timestamp()
    ) RETURNING * INTO stored;
    PERFORM aq_append_durable_case_event(
        tenant,
        p_case_id,
        'PAPER_EXECUTION_RECORDED',
        'durable-execution:' || p_execution_id::text,
        '["object",[["result_digest",["string","' || p_result_digest || '"]]]]'
    );
    RETURN stored;
END;
$$;
REVOKE ALL ON FUNCTION aq_record_paper_execution(
    text,uuid,text,uuid,text,text,text,text,text,jsonb,bigint,text,jsonb
) FROM PUBLIC;

CREATE FUNCTION aq_record_execution_reconciliation(
    p_tenant_id text,
    p_case_id uuid,
    p_account_id text,
    p_execution_id uuid,
    p_result_digest text
) RETURNS case_events
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    tenant text := aq_current_tenant_id();
    stored paper_execution_results;
BEGIN
    IF tenant IS NULL OR p_tenant_id <> tenant THEN
        RAISE EXCEPTION 'reconciliation tenant does not match authenticated database tenant'
            USING ERRCODE = 'AQ004';
    END IF;
    SELECT * INTO stored FROM paper_execution_results
    WHERE tenant_id = tenant
      AND case_id = p_case_id
      AND account_id = p_account_id
      AND execution_id = p_execution_id
      AND result_digest = p_result_digest;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation does not bind an exact durable execution'
            USING ERRCODE = 'AQ006';
    END IF;
    RETURN aq_append_durable_case_event(
        tenant,
        p_case_id,
        'EXECUTION_RECONCILED',
        'durable-reconcile:' || p_execution_id::text,
        '["object",[["result_digest",["string","' || p_result_digest || '"]]]]'
    );
END;
$$;
REVOKE ALL ON FUNCTION aq_record_execution_reconciliation(text,uuid,text,uuid,text)
FROM PUBLIC;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'paper_account_snapshots', 'consumed_risk_decisions', 'paper_execution_results'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_reject_mutation BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION aq_reject_mutation()',
            table_name, table_name
        );
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

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    paper_account_snapshots, consumed_risk_decisions, paper_execution_results
FROM PUBLIC;

COMMIT;
