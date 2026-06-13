-- AgentForge Arena — v0.1 PostgreSQL schema (RAW LAYER ONLY).
-- Framework reference: docs/EVALUATION_FRAMEWORK.md §10.
--
-- This file defines the append-only raw layer plus the minimal immutable parent
-- entities the raw rows reference. Derived/aggregation tables (aggregate_scores,
-- capability_profiles, task_difficulty_estimates, rankings, irt_estimates) are
-- intentionally NOT here — they are recomputable from this layer and stamped
-- with a formula_version, added in v0.2+. See §10.
--
-- Mutation contract: raw tables are INSERT-only. Never UPDATE a run, test
-- result, diff, or score in place; a scoring-formula change inserts new
-- run_scores rows under a new formula_version and retains the old ones.

BEGIN;

-- --------------------------------------------------------------------------- --
-- Immutable parent entities (scores attach to *versions*, never to the mutable
-- task/agent identity).
-- --------------------------------------------------------------------------- --

CREATE TABLE IF NOT EXISTS tasks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS task_versions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id             BIGINT NOT NULL REFERENCES tasks(id),
    semver              TEXT NOT NULL,
    spec_jsonb          JSONB NOT NULL,
    repo_snapshot_hash  TEXT NOT NULL,          -- 'sha256:...'
    manual_difficulty   SMALLINT,
    timeout_s           INTEGER NOT NULL,
    resource_limits     JSONB NOT NULL DEFAULT '{}'::jsonb,
    scoring_recipe      JSONB NOT NULL DEFAULT '{}'::jsonb,
    activity            TEXT,
    scale               TEXT,
    review_state        TEXT NOT NULL DEFAULT 'candidate',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, semver)
);

-- Weighted domain tags for a task version (primary 1.0 / secondary 0.5 / tertiary 0.25).
CREATE TABLE IF NOT EXISTS task_domains (
    task_version_id BIGINT NOT NULL REFERENCES task_versions(id),
    domain          TEXT   NOT NULL,
    axis            TEXT   NOT NULL DEFAULT 'domain',  -- 'domain' | 'activity' | 'scale'
    weight          NUMERIC(4,3) NOT NULL,
    PRIMARY KEY (task_version_id, domain, axis)
);

CREATE TABLE IF NOT EXISTS agents (
    id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    kind  TEXT NOT NULL                          -- 'mock'|'script'|'cli'|'ollama'|'api'
);

CREATE TABLE IF NOT EXISTS agent_versions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_id    BIGINT NOT NULL REFERENCES agents(id),
    semver      TEXT NOT NULL,
    config_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_hash TEXT NOT NULL,                   -- 'sha256:...' of canonical config
    model_id    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, config_hash)
);

-- A planned set of repeated runs of one (agent_version, task_version).
CREATE TABLE IF NOT EXISTS run_groups (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent_version_id  BIGINT NOT NULL REFERENCES agent_versions(id),
    task_version_id   BIGINT NOT NULL REFERENCES task_versions(id),
    planned_runs      INTEGER NOT NULL,
    env_hash          TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------------- --
-- Raw layer (APPEND-ONLY).
-- --------------------------------------------------------------------------- --

CREATE TABLE IF NOT EXISTS runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_group_id    BIGINT NOT NULL REFERENCES run_groups(id),
    idx             INTEGER NOT NULL,            -- 0-based position within the group
    status          TEXT NOT NULL,               -- 'valid'|'timeout'|'agent_error'|'infra_failure'
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    wall_clock_ms   INTEGER,
    cpu_ms          INTEGER,
    mem_peak_mb     INTEGER,
    sampling_seed   BIGINT,                      -- recorded, NOT fixed across runs (§9)
    transcript_hash TEXT NOT NULL,               -- determinism detection (§2)
    manifest_jsonb  JSONB NOT NULL DEFAULT '{}'::jsonb,
    image_digest    TEXT,
    UNIQUE (run_group_id, idx)
);
CREATE INDEX IF NOT EXISTS ix_runs_group       ON runs(run_group_id);
CREATE INDEX IF NOT EXISTS ix_runs_status_void ON runs(status) WHERE status = 'infra_failure';

CREATE TABLE IF NOT EXISTS diffs (
    run_id            BIGINT PRIMARY KEY REFERENCES runs(id),
    patch_ref         TEXT,                      -- content-addressed blob ref (patch text off-DB)
    files_changed     INTEGER NOT NULL,
    lines_added       INTEGER NOT NULL,
    lines_removed     INTEGER NOT NULL,
    touched_protected BOOLEAN NOT NULL,
    files_jsonb       JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS test_results (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES runs(id),
    suite       TEXT NOT NULL,                   -- 'visible'|'hidden'|'regression'
    test_name   TEXT NOT NULL,
    status      TEXT NOT NULL,                   -- 'pass'|'fail'|'error'|'skip'
    duration_ms INTEGER,
    weight      NUMERIC(6,3) NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS ix_test_results_run ON test_results(run_id);

-- Deterministic score of a run under a given scoring formula version.
-- (run_id, formula_version) is unique: a formula change inserts new rows.
CREATE TABLE IF NOT EXISTS run_scores (
    run_id          BIGINT NOT NULL REFERENCES runs(id),
    formula_version TEXT NOT NULL DEFAULT 'v0.1',
    gates_jsonb     JSONB NOT NULL,              -- {setup_ok, diff_exists, scope_ok, regression_pass, no_timeout}
    gate_product    SMALLINT NOT NULL,           -- G in {0,1}
    t_hidden        NUMERIC(9,6) NOT NULL,       -- T_hidden
    q_score         NUMERIC(9,6) NOT NULL,       -- Q
    final_score     NUMERIC(9,6) NOT NULL,       -- S
    functional_pass BOOLEAN NOT NULL,            -- X
    voided          BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, formula_version)
);

COMMIT;
