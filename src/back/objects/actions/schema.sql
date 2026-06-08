-- Kinetic Action layer tables. Idempotent. Applied into the active
-- Lakebase registry schema (search_path is set by the pooled connection).

CREATE TABLE IF NOT EXISTS action_log (
    action_id        uuid PRIMARY KEY,
    action_type      text NOT NULL,
    domain           text NOT NULL,
    object_type      text NOT NULL,
    object_id        text NOT NULL,
    params           jsonb NOT NULL,
    actor            text NOT NULL,
    actor_kind       text NOT NULL,
    status           text NOT NULL,
    before           jsonb,
    after            jsonb,
    approved_by      text,
    parent_action_id uuid,
    created_at       timestamptz NOT NULL DEFAULT now(),
    applied_at       timestamptz
);

CREATE TABLE IF NOT EXISTS ontology_overlay (
    domain      text NOT NULL,
    object_type text NOT NULL,
    object_id   text NOT NULL,
    property    text NOT NULL,
    value       jsonb NOT NULL,
    action_id   uuid NOT NULL,
    status      text NOT NULL,
    valid_from  timestamptz NOT NULL DEFAULT now(),
    valid_to    timestamptz,
    PRIMARY KEY (domain, object_type, object_id, property, valid_from)
);

CREATE INDEX IF NOT EXISTS ontology_overlay_current_idx
    ON ontology_overlay (domain, object_type, object_id, property)
    WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS action_effects_outbox (
    effect_id    uuid PRIMARY KEY,
    action_id    uuid NOT NULL,
    effect_name  text NOT NULL,
    payload      jsonb NOT NULL,
    status       text NOT NULL,
    attempts     int NOT NULL DEFAULT 0,
    last_error   text,
    next_attempt_at timestamptz NOT NULL DEFAULT now()
);
