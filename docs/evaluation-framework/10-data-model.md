## 10. Data model (PostgreSQL)

The schema is split into two layers with different mutation rules:

1. **Raw layer** — what happened: `runs`, `trace_events`, `command_logs`, `test_results`, `diffs`. **Append-only.** Rows are written once by the harness and never updated or recomputed. (One scoped exception: `runs` doubles as the Section 9.3 work queue, so its lifecycle fields — `status`, `claimed_by`/`claimed_at`, `started_at`/`finished_at` — advance from `queued` to exactly one terminal status; every measurement field is still written once.) This is the audit substrate; every score must be re-derivable from it.
2. **Derived layer** — what it means: `run_scores`, `aggregate_scores`, `task_difficulty_estimates`, `capability_profiles`, `agent_scope_metrics`, `rankings`, `irt_estimates`. **Fully recomputable** from the raw layer, and every row is stamped with `formula_version`. A change to any scoring formula (gates, Q weighting, Wilson z, shrinkage) means a **new** `formula_version` string, a full recompute, and **retention of old rows** for audit. Derived rows are never UPDATEd in place; the only write is INSERT, the only correction is a new version.

This rule is what makes "the leaderboard changed" always answerable: either new raw data arrived, or `formula_version` changed — never silent mutation.

All identifiers are `bigint GENERATED ALWAYS AS IDENTITY`. Content hashes are `text` in the form `sha256:<hex>`. Scores are `numeric(9,6)` (exact, reproducible across replicas; we never need float speed in OLTP paths).

### 10.1 Core tables (DDL sketches)

```sql
-- ============ TASK IDENTITY & VERSIONING ============
-- A task is a stable slug; everything gradable hangs off an immutable version.
CREATE TABLE tasks (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug                text NOT NULL UNIQUE,           -- 'fix-auth-redirect'
  created_at          timestamptz NOT NULL DEFAULT now(),
  current_version_id  bigint                          -- FK -> task_versions, set after first version
);

-- Canonical task lifecycle = Section 5.4's state machine, adopted verbatim
-- because ranking-inclusion logic depends on it: 'calibrating' and
-- 'quarantined' versions are excluded from all rankings and domain scores
-- (5.4, 6.6). 'candidate' covers Section 8.1's authoring states
-- (draft/in_review); the 8.2 activation gates govern candidate -> calibrating,
-- 5.4's run-quota rule governs calibrating -> active, and the FLAKY /
-- negative-discrimination flags auto-set 'quarantined'.
CREATE TYPE review_state AS ENUM ('candidate','calibrating','active','quarantined','retired');

CREATE TABLE task_versions (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id              bigint NOT NULL REFERENCES tasks(id),
  semver               text NOT NULL,                 -- '1.2.0'; any spec/test change bumps it
  spec_jsonb           jsonb NOT NULL,                -- prompt, visible-test list, protected paths
  repo_snapshot_hash   text NOT NULL,                 -- content-addressed pristine repo (blob store)
  manual_difficulty    smallint,                      -- 1..5 author estimate; superseded by empirical/IRT
  timeout_s            integer NOT NULL,
  resource_limits_jsonb jsonb NOT NULL,               -- cpu, mem, net=off
  scoring_recipe_jsonb jsonb NOT NULL,                -- hidden-test weights, regression suite id
  review_state         review_state NOT NULL DEFAULT 'candidate',
  pack_id              bigint REFERENCES benchmark_packs(id),
  UNIQUE (task_id, semver)
);
-- Scores attach to task_versions, never tasks: changing a hidden test
-- changes the measurement instrument, so old results must not commingle.

-- ============ EXECUTION ============
-- Lifecycle states first, then Section 1.5's four terminal statuses as the
-- subset every run ends in. The queue of Section 9.3 lives in this column:
-- rows are INSERTed 'queued' at enqueue, claimed 'claimed' by a worker via
-- FOR UPDATE SKIP LOCKED, advance to 'running', and finish in exactly one
-- terminal status. Only terminal rows feed scoring.
CREATE TYPE run_status AS ENUM ('queued','claimed','running',
                                'valid','timeout','agent_error','infra_failure');

CREATE TABLE run_groups (                             -- one (agent_version, task_version) campaign
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_version_id bigint NOT NULL REFERENCES agent_versions(id),
  task_version_id  bigint NOT NULL REFERENCES task_versions(id),
  pack_id          bigint REFERENCES benchmark_packs(id),
  planned_runs     smallint NOT NULL,                 -- 5 default; 10 after escalation; 2 deterministic
  env_hash         text NOT NULL,                     -- hash of image digest + limits + harness version
  status           text NOT NULL DEFAULT 'pending',   -- pending|running|complete|aborted
  created_at       timestamptz NOT NULL DEFAULT now()
);
-- Escalation mechanics (n = 5 -> 10 when 0.2 < p-hat < 0.8, contract decision
-- 7): escalation UPDATEs planned_runs in place on this same group and enqueues
-- runs idx 5..9 under the same run_group_id — a second run_group is never
-- created for the same campaign, so latest-group queries cannot double-count.
-- The group's aggregate_scores row is superseded by a recompute at the same
-- formula_version once the new runs land (see aggregate_scores below).
CREATE INDEX rg_pack_idx ON run_groups (pack_id, agent_version_id, task_version_id, created_at DESC);

CREATE TABLE runs (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_group_id   bigint NOT NULL REFERENCES run_groups(id),
  idx            smallint NOT NULL,                   -- 0..planned_runs-1 (retries of INFRA_FAILURE reuse idx)
  attempt        smallint NOT NULL DEFAULT 0,         -- 0 first try; 1..2 INFRA_FAILURE retries (9.3 retry policy)
  run_key        text NOT NULL,                       -- idempotency key per 9.2; enqueue is INSERT ... ON CONFLICT DO NOTHING
  status         run_status NOT NULL DEFAULT 'queued',
  priority       smallint NOT NULL DEFAULT 0,         -- serves 9.3's ORDER BY priority DESC, created_at
  created_at     timestamptz NOT NULL DEFAULT now(),  -- enqueue time
  claimed_by     text, claimed_at timestamptz,        -- worker claim + heartbeat reclaim (9.3)
  started_at     timestamptz,                         -- NULL until execution begins
  finished_at    timestamptz,
  wall_clock_ms  bigint, cpu_ms bigint, mem_peak_mb integer,   -- separate axes, never inside S
  sampling_seed  bigint,                              -- recorded for exact replay; determinism is confirmed by identical
                                                      -- transcript hashes ACROSS runs with DISTINCT sampling seeds (2.8, 9.5)
  transcript_hash text,                               -- h_i = sha256(command transcript || final diff) (2.8); NULL until capture
  manifest_jsonb jsonb,                               -- exact inputs: prompt hash, env, tool list; NULL until execution starts
  image_digest   text NOT NULL,                       -- docker image actually used
  UNIQUE (run_key, attempt)                           -- re-submitting a request is a no-op at attempt 0; retries reuse run_key at attempt+1
);
CREATE UNIQUE INDEX runs_group_idx ON runs (run_group_id, idx)
  WHERE status <> 'infra_failure';                    -- exactly one live-or-scored run per idx; voided rows excluded so retries can reuse idx
CREATE INDEX runs_group_lookup_idx ON runs (run_group_id, idx);  -- drilldowns including voided rows
CREATE INDEX runs_queue_idx ON runs (priority DESC, created_at)
  WHERE status = 'queued';                            -- serves the 9.3 claim query
CREATE INDEX runs_status_idx ON runs (status) WHERE status = 'infra_failure'; -- alerting scan

-- ============ TRACES (high volume) ============
CREATE TABLE trace_events (
  run_id       bigint NOT NULL,
  seq          integer NOT NULL,
  ts           timestamptz NOT NULL,
  type         text NOT NULL,                          -- 'tool_call','file_edit','message',...
  payload_jsonb jsonb NOT NULL,
  PRIMARY KEY (run_id, seq)
) PARTITION BY HASH (run_id);
-- 16 hash partitions created at install time:
--   CREATE TABLE trace_events_p00 PARTITION OF trace_events FOR VALUES WITH (MODULUS 16, REMAINDER 0); ...
-- WHY HASH(run_id), not RANGE(ts): every read of this table is a single-run
-- drilldown (WHERE run_id = $1), so pruning by run_id hits exactly one
-- partition. RANGE-by-time's only advantage is cheap DROP PARTITION for
-- retention — but the raw layer is append-only and retained indefinitely for
-- audit, so we never bulk-drop by time. HASH also spreads insert hotspots
-- across partitions when many sandboxes stream concurrently.
-- LARGE-PAYLOAD POLICY: payload_jsonb is capped at 8 KB at ingest. Larger
-- payloads (full file contents, big tool outputs) are written to the blob
-- store and the row stores {"blob_ref":"sha256:...","bytes":N,"truncated_preview":"..."}.
-- Keeps TOAST churn and backup size bounded while preserving full fidelity.

-- ============ DERIVED: PER-RUN SCORE ============
CREATE TABLE run_scores (
  run_id          bigint NOT NULL REFERENCES runs(id),
  gates_jsonb     jsonb NOT NULL,    -- {"setup_ok":true,"diff_exists":true,"scope_ok":true,"regression_pass":true,"no_timeout":true}
  gate_passed     boolean NOT NULL,  -- G = product of gates
  functional_pass boolean NOT NULL,  -- X = 1 iff G=1 AND all hidden tests pass
  t_hidden        numeric(9,6) NOT NULL,
  q_score         numeric(9,6) NOT NULL,
  final_score     numeric(9,6) NOT NULL,  -- S = G * T_hidden * (0.85 + 0.15*Q)
  formula_version text NOT NULL,
  PRIMARY KEY (run_id, formula_version)
);

-- ============ DERIVED: PER-GROUP AGGREGATE ============
CREATE TABLE aggregate_scores (
  run_group_id   bigint NOT NULL REFERENCES run_groups(id),
  formula_version text NOT NULL,
  n_valid smallint NOT NULL, n_pass smallint NOT NULL,
  pass_rate numeric(9,6) NOT NULL,         -- p-hat = c/n
  wilson_low numeric(9,6) NOT NULL, wilson_high numeric(9,6) NOT NULL,
  mean_s numeric(9,6), median_s numeric(9,6), std_s numeric(9,6),
  min_s numeric(9,6), max_s numeric(9,6),
  stability numeric(9,6),                  -- max(0, 1 - 2s)
  pass_at_k_jsonb jsonb,                   -- {"1":0.4,"3":0.9,...} unbiased estimator (n=5, c=2)
  timeout_rate numeric(9,6),
  conservative_s numeric(9,6),             -- one-sided 95% t lower bound on mean S (2.9)
  reliability numeric(9,6),                -- (# runs with status not in {TIMEOUT, AGENT_ERROR}) / n (2.7)
  infra_void_rate numeric(9,6),            -- voided attempts / total attempts (1.5)
  deterministic boolean NOT NULL DEFAULT false,  -- all n transcript hashes identical (2.8)
  bimodal boolean NOT NULL DEFAULT false,        -- bimodality flag (2.8)
  computed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_group_id, formula_version, computed_at)
);
-- INSERT-only, per the derived-layer rule: a recompute at the SAME
-- formula_version (the n = 5 -> 10 escalation adds runs to an existing group)
-- inserts a new row distinguished by computed_at. Readers resolve to the
-- latest computed_at per (run_group_id, formula_version) through this view,
-- which every query in 10.3 joins instead of the bare table:
--   CREATE VIEW aggregate_scores_current AS
--     SELECT DISTINCT ON (run_group_id, formula_version) *
--     FROM aggregate_scores ORDER BY run_group_id, formula_version, computed_at DESC;
```

### 10.2 Remaining tables (bullet specs)

- **domains**: `id PK, key text UNIQUE, name text, axis enum('domain','activity','scale'), parent_id bigint FK -> domains(id) NULL`. Three orthogonal taxonomies in one table, discriminated by `axis`. `parent_id` is reserved for future taxonomy versions and is unused by v0.x/v1.0 scoring: Section 4.1's vocabulary is deliberately flat — the K = 8 domains (e.g. `backend` and `api-design`) are peers that the macro-average (4.6) treats as independent components, so no hierarchy may relate two scored domains or the same runs would be double-counted.
- **task_domains**: `task_version_id FK, domain_id FK, weight numeric(3,2) CHECK (weight IN (1.0, 0.5, 0.25))`, `PK (task_version_id, domain_id)`. App layer enforces max 3 tags and exactly one weight-1.0 primary. Index `(domain_id)` for profile queries.
- **benchmark_packs**: `id PK, name text, semver text, lockfile_jsonb jsonb` (exact `task_version_id` + `repo_snapshot_hash` list), `pack_hash text UNIQUE` (hash of the lockfile — two packs with identical content are the same pack). Leaderboards are always scoped to a `pack_hash`; cross-pack comparison is forbidden at the query layer.
- **agents**: `id PK, name text UNIQUE, kind enum('mock','script','cli','ollama','api')`.
- **agent_versions**: `id PK, agent_id FK, semver text, config_jsonb jsonb, config_hash text` (hash of config + model weights digest where available — any config change is a new measurable entity), `model_id text NULL, created_at`. `UNIQUE (agent_id, config_hash)`.
- **command_logs**: `run_id FK, seq int, cmd_text text, exit_code int, duration_ms int, stdout_ref text, stderr_ref text`, `PK (run_id, seq)`. `stdout_ref`/`stderr_ref` are blob-store hashes, **not** inline text: a single noisy `npm install` emits 1–5 MB; at 5,000 runs x ~100 commands that is potentially hundreds of GB which would wreck Postgres backups, vacuum, and cache hit rates for zero query value (we never SQL-search stdout; we fetch it whole for one run).
- **test_results**: `run_id FK, suite enum('visible','hidden','regression'), test_name text, status enum('pass','fail','error','skip'), duration_ms int, weight numeric(6,4)`, `PK (run_id, suite, test_name)`. `T_hidden` = sum(weight where pass)/sum(weight) over `suite='hidden'`, computed into `run_scores`. Visible rows are stored for diagnostics but never scored.
- **diffs**: `run_id PK/FK, patch_ref text` (blob store), `files_changed int, lines_added int, lines_removed int, touched_protected bool, files_jsonb jsonb` (per-file stats). `touched_protected` feeds the `scope_ok` gate.
- **task_difficulty_estimates**: `task_version_id FK, method enum('manual','empirical','irt'), difficulty numeric, discrimination numeric NULL, se numeric NULL, n_agents int, n_runs int, computed_at`, `UNIQUE (task_version_id, method, computed_at)`. All three methods coexist; UI shows the best available (irt > empirical > manual).
- **capability_profiles**: `agent_version_id FK, domain_id FK, formula_version text, score, lcb, ucb, n_tasks int, n_runs_effective numeric` (Kish n_eff), `stability, computed_at`, `UNIQUE (agent_version_id, domain_id, formula_version)`.
- **agent_scope_metrics**: `agent_version_id FK, scope_kind enum('pack','domain','task_filter'), scope_value text` (the pack hash, domain key, or canonical filter hash; the pair surfaces as the opaque `:scope` id in Section 7.4's queries), `pack_hash text, formula_version text, anchor_version text`, the five objectives `g_pass, g_speed, g_cost, g_stab, g_mem numeric(9,6)`, the preset auxiliaries `g_worst, g_scope, g_secclean, g_regr, g_par numeric(9,6) NULL` (NULL where the scope lacks the inputs, e.g. no reference solution for `g_par`), `n_valid_runs int, computed_at`, `UNIQUE (agent_version_id, scope_kind, scope_value, pack_hash, formula_version, anchor_version)`. The materialized objective-vector table behind Section 7's frontier scatters, epsilon-constraint queries, and presets; recomputed on run-group completion like `capability_profiles`, INSERT-only per the derived-layer rule. Index `(scope_kind, scope_value, pack_hash)`: the epsilon-constraint queries filter by scope, then sort by one objective.
- **rankings**: `id PK, scope text` ('pack:<hash>' or 'pack:<hash>:domain:<key>'), `method text` ('wilson_lcb','irt_theta'), `snapshot_at timestamptz, entries_jsonb jsonb` (ordered array with scores and intervals), `formula_version text`. Immutable snapshots — the UI renders a snapshot, never a live query, so a leaderboard screenshot is always reproducible.
- **irt_estimates**: `agent_version_id bigint NULL, task_version_id bigint NULL, domain_id bigint NULL, parameter enum('theta','b','gamma'), mean, sd, ci_low, ci_high, fit_run_id bigint` (FK to a fit-metadata table recording PyMC version, seed, and data snapshot hash). CHECK constraints per parameter: `theta` sets only `agent_version_id`; `b` sets only `task_version_id`; `gamma` (agent x domain interaction) sets `agent_version_id` + `domain_id`. Pairwise `P(theta_a > theta_b)` matrices are derived from posterior draws stored as a blob ref on the fit-metadata row, not in this table.

### 10.3 Query patterns

**Leaderboard** (the v0.1 headline per Section 6.6: per-domain pooled p-hat_k with Kish n_eff Wilson intervals, macro-averaged over domains with >= 5 tasks, ranked by the macro-averaged LCB). The Wilson lower bound is computed inline:

```
wilson_low = ( p + z^2/(2n) - z * sqrt( p(1-p)/n + z^2/(4n^2) ) ) / ( 1 + z^2/n )
```

where `p = p-hat_k` is the domain's pooled pass rate and `n` its Kish n_eff, `z = 1.96`. Worked anchor: n=5, c=3, p=0.6 -> numerator 0.6 + 0.38416 - 1.96*sqrt(0.048 + 0.038416) = 0.40798, denominator 1.76832 -> **0.2307**; upper bound -> **0.8824**. Matches the contract anchor. There is deliberately **no** all-task pooled rate here: pooling every task for an agent into one binomial is the micro-average Section 4.6 rejects (dominated by whichever domain has the most tasks, so re-balancing the bank moves every agent's rank) and treats correlated, unequally difficult trials as i.i.d., narrowing the interval dishonestly.

```sql
WITH latest_rg AS (
  SELECT DISTINCT ON (agent_version_id, task_version_id)
         id, agent_version_id, task_version_id
  FROM run_groups
  WHERE pack_id = :pack_id AND status = 'complete'
  ORDER BY agent_version_id, task_version_id, created_at DESC
), per_domain AS (   -- same Kish pooling as the domain-profile query below
  SELECT rg.agent_version_id, td.domain_id,
         COUNT(DISTINCT rg.task_version_id)                              AS n_tasks,
         SUM(td.weight*ag.n_pass)/NULLIF(SUM(td.weight*ag.n_valid),0)    AS p_k,
         POWER(SUM(td.weight*ag.n_valid),2)
           / NULLIF(SUM(td.weight*td.weight*ag.n_valid),0)               AS n_eff
  FROM latest_rg rg
  JOIN aggregate_scores_current ag ON ag.run_group_id = rg.id
                          AND ag.formula_version = :fv
  JOIN task_domains td     ON td.task_version_id = rg.task_version_id
  JOIN domains d           ON d.id = td.domain_id AND d.axis = 'domain'
  GROUP BY rg.agent_version_id, td.domain_id
)
SELECT a.name, av.semver,
       COUNT(*) AS domains_covered,        -- 4.6 non-comparability rule: only compare equal domain sets
       AVG( (p_k + 1.9208/n_eff - 1.96*sqrt(p_k*(1-p_k)/n_eff + 0.9604/(n_eff*n_eff)))
            / (1 + 3.8416/n_eff) )                                       AS macro_lcb
FROM per_domain pd
JOIN agent_versions av ON av.id = pd.agent_version_id
JOIN agents a          ON a.id = av.agent_id
WHERE pd.n_tasks >= 5 AND pd.n_eff > 0     -- coverage floor per 6.6
GROUP BY a.name, av.semver
ORDER BY macro_lcb DESC;
```

Served by `rg_pack_idx` plus the `aggregate_scores` unique index and the `task_domains` PK; sub-millisecond at our volumes. Production leaderboards read the `rankings` snapshot this query produces, with `domains_covered` carried into the snapshot so the UI can grey out non-comparable rows.

**Domain profile** (per-domain pooled pass rate p-hat_k and Kish n_eff for one agent):

```
p_hat_k = SUM(w_tk * c_t) / SUM(w_tk * n_t)
n_eff   = ( SUM(w_tk * n_t) )^2 / SUM(w_tk^2 * n_t)
```

`w_tk` = the task's weight for domain k (1.0/0.5/0.25), `c_t`/`n_t` from `aggregate_scores`. Worked example: domain k has task A (w=1.0, n=10, c=7) and task B (w=0.5, n=10, c=4) -> p_hat_k = (7 + 2)/(10 + 5) = 0.6; n_eff = 15^2 / (1.0*10 + 0.25*10) = 225/12.5 = **18** (less than the raw 20 because unequal weights cost information). n_eff is then used as n in the Wilson formula above.

```sql
WITH latest_rg AS (         -- same latest-complete-group-per-task rule as the leaderboard:
  SELECT DISTINCT ON (task_version_id) id, task_version_id   -- a re-evaluation must supersede,
  FROM run_groups                                            -- never double-count, its task
  WHERE agent_version_id = :av AND pack_id = :pack_id AND status = 'complete'
  ORDER BY task_version_id, created_at DESC
)
SELECT td.domain_id, d.key,
       SUM(td.weight*ag.n_pass)/NULLIF(SUM(td.weight*ag.n_valid),0)           AS p_hat_k,
       POWER(SUM(td.weight*ag.n_valid),2)
         / NULLIF(SUM(td.weight*td.weight*ag.n_valid),0)                      AS n_eff
FROM latest_rg rg
JOIN aggregate_scores_current ag ON ag.run_group_id = rg.id AND ag.formula_version = :fv
JOIN task_domains td     ON td.task_version_id = rg.task_version_id
JOIN domains d           ON d.id = td.domain_id AND d.axis = 'domain'
GROUP BY td.domain_id, d.key;
```

**Task health** (pooled difficulty with Laplace shrinkage, plus discrimination inputs):

```
d_t = 1 - (c_pool + 1) / (n_pool + 2)
```

`c_pool`/`n_pool` pooled over all agents. Worked example: c_pool=37, n_pool=100 -> d_t = 1 - 38/102 = **0.6275**. The same query also emits the per-(agent, task) p-hat matrix consumed by the Python job that computes corrected point-biserial discrimination (item-total with the item removed — done in Python, not SQL, because it needs the agent-level total across all tasks).

```sql
SELECT rg.task_version_id, t.slug,
       SUM(ag.n_pass) AS c_pool, SUM(ag.n_valid) AS n_pool,
       1 - (SUM(ag.n_pass)+1.0)/(SUM(ag.n_valid)+2.0) AS d_t,
       jsonb_object_agg(rg.agent_version_id, ag.pass_rate) AS per_agent_phat
FROM run_groups rg
JOIN aggregate_scores_current ag ON ag.run_group_id = rg.id AND ag.formula_version = :fv
JOIN task_versions tv ON tv.id = rg.task_version_id JOIN tasks t ON t.id = tv.task_id
WHERE rg.pack_id = :pack_id
GROUP BY rg.task_version_id, t.slug;
```

**Run drilldown** (one run: gates, score, tests, commands, trace). Four indexed point lookups, all on `run_id` PKs:

```sql
SELECT r.*, rs.gates_jsonb, rs.t_hidden, rs.q_score, rs.final_score,
       d.files_changed, d.lines_added, d.lines_removed, d.touched_protected
FROM runs r
LEFT JOIN run_scores rs ON rs.run_id = r.id AND rs.formula_version = :fv
LEFT JOIN diffs d       ON d.run_id = r.id
WHERE r.id = :run_id;

SELECT suite, test_name, status, duration_ms, weight
FROM test_results WHERE run_id = :run_id ORDER BY suite, test_name;

SELECT seq, cmd_text, exit_code, duration_ms, stdout_ref
FROM command_logs WHERE run_id = :run_id ORDER BY seq;

SELECT seq, ts, type, payload_jsonb
FROM trace_events WHERE run_id = :run_id ORDER BY seq;  -- prunes to 1 of 16 partitions
```

### 10.4 Volumes and when structure actually matters

One full pack evaluation: 50 tasks x 10 agents x 10 runs = **5,000 runs**. Per run: ~500–2,000 `trace_events` (2.5M–10M rows), ~50–200 `command_logs` (250k–1M), ~40 `test_results` (200k), 1 diff, 1–3 `run_scores` rows across formula versions. Twenty such evaluations over a year is ~100k runs and ~100–200M trace rows at the extreme — still comfortably Postgres on a single machine with the indexes above. Decisions:

- Hash-partition `trace_events` from day one (free at create time, painful to retrofit). Everything else stays unpartitioned until a table exceeds ~50M rows.
- Indexes beyond PKs: `rg_pack_idx`, `runs(run_group_id, idx)` (plain, plus the partial UNIQUE excluding voided rows), the partial queue index `runs(priority DESC, created_at) WHERE status='queued'` (the 9.3 claim query), `aggregate_scores(run_group_id, formula_version, computed_at)` (the UNIQUE), `task_domains(domain_id)`, `capability_profiles(agent_version_id, formula_version)`, `agent_scope_metrics(scope_kind, scope_value, pack_hash)` (Section 7.4's epsilon-constraint queries), partial index on `runs(status) WHERE status='infra_failure'`. Add nothing speculatively; every listed query is covered.
- Autovacuum is a non-issue on the raw layer (append-only, no dead tuples); derived tables churn only on recompute, which is batch INSERT.

### 10.5 What stays out of Postgres

Content-addressed blob store on local disk (`/var/agentforge/blobs/sha256/ab/cd/<hash>`), optionally MinIO when multi-node — both fully offline. Stored there, referenced by hash from Postgres: **patches** (`diffs.patch_ref`), **stdout/stderr** (`command_logs.*_ref`), **repo snapshots** (`task_versions.repo_snapshot_hash`), **oversized trace payloads**, **PyMC fit artifacts**. Content addressing gives free deduplication (identical `npm install` output across 5,000 runs is stored once) and makes the clean-room grader trivially verifiable: the grader fetches the snapshot by hash, applies the patch by hash, and the hashes appearing in `run_scores` provenance prove exactly what was graded. Blobs are immutable; garbage collection is mark-and-sweep against all `*_ref` columns, run manually.

### Limitations

- **`runs.idx` uniqueness among non-voided rows is enforced by the partial unique index** (`WHERE status <> 'infra_failure'`), but the retry budget (`attempt <= 2`) and the rule that a retry may be enqueued only after its predecessor is voided live in the application; a harness bug could mint extra attempts, which the aggregation job detects and refuses to score — detection of that class remains post-hoc.
- **Per-domain Wilson pooling treats runs within a domain as i.i.d. Bernoulli**, ignoring task-level clustering (runs on the same task are correlated), and Kish n_eff corrects for unequal weights, not for between-task difficulty variance — so each domain interval, and the macro-averaged LCB built from them, is somewhat anti-conservative (Section 4's exchangeability caveat). This is a v0.1 accepted simplification; v1.0 IRT intervals replace it as the headline once enough data accumulates.
- **`jsonb` columns (`spec_jsonb`, `manifest_jsonb`, `gates_jsonb`) trade schema enforcement for flexibility.** Their shapes are validated by Pydantic at the API boundary, not by the database; a rogue direct write can store garbage. We accept this because gate definitions will evolve faster than we want to run migrations.
- **The blob store and Postgres can drift**: a row can reference a hash whose blob was lost (disk failure) since there is no cross-system transaction. Writes are ordered blob-first, row-second, which prevents dangling refs from crashes, but does not prevent out-of-band blob deletion. The GC job doubles as a referential-integrity audit.
- **Hash partitioning fixes the partition count at 16.** Repartitioning later requires a table rewrite. At our worst-case volume (~12M rows/partition) this is fine, but a 100x usage surprise would force a maintenance window.
- **Old `formula_version` derived rows accumulate forever** by design; after many formula iterations the derived tables may exceed the raw tables in row count. Acceptable at our scale; a retention policy for superseded versions is deliberately deferred until it is a measured problem.
