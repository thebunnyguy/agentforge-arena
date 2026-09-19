# ATLAS pre-integration observation — raw subsystem audits

**Subject:** frozen ATLAS branch `codex/phase-0-evaluation-integrity @ 1e1a788cadd5ed35fed9fe37d8e8ebbba922bf07`,
observed as an isolated detached worktree BEFORE any ATLAS content was merged into the integration branch.

**Method:** seven independent read-only auditors (one per subsystem, plus a cross-cutting task-version auditor) each read the
implementation (not commit messages) and reported claims with `file:line` evidence and the tests that actually prove them; a
completeness critic then spot-checked their claims against the code. Auditors were forbidden from writing to the frozen tree and
ran any empirical probes only on private copies. This file is the unedited structured output (rendered to Markdown); the
synthesised baseline is `../ATLAS_PRE_INTEGRATION_BASELINE.md`.

**Confidence vocabulary:** `verified` = read in code and (where stated) confirmed by a test or a probe; `read-only-inferred` =
read in code only; `uncertain`.

## Provider/backend semantics, OpenAI-compatible path, runner changes, raw persistence (RunStore/RunRecord) in frozen ATLAS (1e1a788)

**Providers.** Three kinds, defined once as `BackendKind = Literal["mock","ollama","openai_compat"]` (afa_api/schemas.py:25). Default base URLs live in `DEFAULT_BACKEND_URLS` (schemas.py:29-32: ollama http://localhost:11434, openai_compat http://localhost:1234) and are duplicated as string literals in worker.py:61/75, routes_jobs.py (verify, ~line 353) and the two agent dataclasses. `Backend` (schemas.py:39-66, extra=forbid) rejects userinfo, query, fragment and non-http(s) URLs, then rstrips "/". Nothing restricts the host to localhost ("local-only" is prose only). `Settings.ollama_base_url/openai_base_url/default_backend` are stored but never read by job creation or the worker (inert).

**Worker instantiation** (worker.py:56-91): mock -> `MockAgent` with reference-file overlay; ollama -> `afa.OllamaAgent`; openai_compat -> `afa.OpenAICompatAgent`, each with model, base_url, temperature, base_seed and request_timeout from `job.params`. The agent factory is created from `job.params`, not from the snapshot (worker.py:315).

**openai_compat is real.** `openai_chat_generate` (runner/afa_runner/agents_openai.py:33-47) POSTs JSON `{model, messages:[{role:user,content:prompt}], temperature, seed, stream:false}` to `base_url.rstrip("/") + "/v1/chat/completions"` with only a Content-Type header (no Authorization anywhere) and returns `body["choices"][0]["message"]["content"]`. `OpenAICompatAgent` subclasses `OllamaAgent` and overrides only `_default_generate` (agents_openai.py:64-72), so there is no path to /api/generate or /api/chat from that class. The dispatch bug was on MASTER: `factory_for` sent both "ollama" and "openai_compat" to `ollama_agent_factory`, so openai_compat silently used /api/generate. ATLAS fixes that in worker.py, not in agents_ollama.py. agents_openai.py is byte-identical to master; the only agents_ollama.py change is the new `set_run_seed()` (lines 107-115: sets base_seed and resets `_call` to 0).

**Seeds.** The worker calls `_set_effective_seed(agent, base_seed + idx)` before every trial (worker.py:317). This is deterministic per position and resume-safe. Mock agents have no setter, so nothing happens.

**Error classification.** `_INFRA_ERRORS` (agents_ollama.py:33-39) includes `URLError`, and `HTTPError` subclasses `URLError` (confirmed in the probe). Every HTTP 4xx/5xx, including a 404 from a wrong base URL such as one already ending in /v1 (which yields /v1/v1/chat/completions), a 401 or an unknown model, therefore becomes INFRA_FAILURE (voided, excluded from n). A 200 response with a malformed body (KeyError, JSONDecodeError, or content None) raises outside `_INFRA_ERRORS` and becomes AGENT_ERROR (counted as a loss). `run_once` checks timeout BEFORE infra (pipeline.py:108-121), so a stalled server whose call exceeds `task.timeout_s` (20/60/120 s vs default request_timeout 180 s) is TIMEOUT, not voided.

**Provenance.** `build_snapshot` (jobs.py:245-272), stored as `evaluation_jobs.snapshot_json`, records model, backend {kind, effective base_url (None for mock)}, generation {base_seed, temperature, request_timeout_s, seed_provenance ("requested" or "unavailable" for mock), timeout_provenance}, tasks [{task_id, task_version, task_digest}] and repeats. `evaluation_report.py` projects this into the JSON and Markdown report (provider = backend.kind, backend, generation). It falls back to `params_json` and adds "unavailable" limitations. Not captured: served-model digest, num_ctx/max_tokens/top_p, per-trial effective seed (only in the transcript, which is not persisted), or provider in the raw `runs` row (`runs.agent` = model name only).

**RunStore.** `RunRecord.run_id: int|None = None` was inserted BEFORE `grade_report` (pipeline.py:45). `load_runs` selects `r.id` and sets `run_id` (store.py:283, 330). `save_run` ignores `record.run_id` and returns `lastrowid`. `save_run` gained keyword-only `commit` and `job_id`, savepoint-based rollback, and a "borrowed connection" mode (`connection=`, `_owns_conn`, so `close()` is a no-op). `open_readonly` was added (`mode=ro` URI). The `runs.job_id` column was added to `SQLITE_SCHEMA` (store.py:60). There are no other new helper queries. No test asserts `run_id` on load or default None.

**Task version.** `runs.task_id` = `task.id` and `runs.task_version` = `task.version` (pipeline.py:153-155), taken from the `Task` that `run_once` was given. In the worker that Task is `afa.load_task(TASKS_DIR/task_id)` (worker.py:133), whose `task.version` is checked equal to the snapshot's `task_version` and whose digest is checked against the snapshot's `task_digest` (worker.py:135-141), so the written value equals the snapshot version. CLI examples (eval_persist.py, eval_pack.py etc.) write `load_task(...).version` from disk at run time with no snapshot.

### Guarantees (claim / evidence / proven-by / confidence)

- **kind=openai_compat in the worker instantiates OpenAICompatAgent and every default generation call is POST {base_url}/v1/chat/completions (stream=false, model/temperature/seed in payload, Content-Type only, no auth header); no code path in OpenAICompatAgent calls /api/generate or /api/chat.**  
  evidence: afa_api/worker.py:72-91; runner/afa_runner/agents_openai.py:33-47,50-72  
  proven by: tests/test_a2_boundaries.py::test_default_openai_factory_uses_real_resumed_transport (real ThreadingHTTPServer on 127.0.0.1, only urlopen wrapped to record timeout; asserts path /v1/chat/completions, model, seeds [700,701], temp 0.23, timeout 7); tests/test_evaluation_identity.py (factory type + request_timeout); runner/tests/test_agents_openai.py::test_openai_payload_shape_and_response_parsing (monkeypatched urlopen)  
  confidence: `verified`
- **kind=ollama uses OllamaAgent -> POST {base_url}/api/generate with options {temperature, seed}, stream=false.**  
  evidence: runner/afa_runner/agents_ollama.py:60-85; afa_api/worker.py:60-69  
  proven by: none (runner/tests/test_agents_ollama.py:7 states ollama_generate is never exercised; only factory type/timeout is checked in tests/test_evaluation_identity.py)  
  confidence: `verified`
- **Per-position seed is deterministic and resume-safe: seed = job.params.base_seed + idx set via set_run_seed before each trial, resetting the call counter, for agents that implement it (Ollama and OpenAICompat, not Mock).**  
  evidence: afa_api/worker.py:116-119,317; runner/afa_runner/agents_ollama.py:107-115,122-123  
  proven by: tests/test_a2_boundaries.py::test_default_openai_factory_uses_real_resumed_transport (resumed position gets 701); tests/test_evaluation_identity.py provider factory test asserts base_seed=207,_call=0  
  confidence: `verified`
- **Backend base_url is validated at API/model level: no credentials, no query/fragment, http(s) absolute URL; extra fields (e.g. api_key) forbidden; trailing slash stripped. No Authorization header is ever sent.**  
  evidence: afa_api/schemas.py:39-66; grep shows no Authorization/api_key use in runner or afa_api  
  proven by: tests/test_evaluation_identity.py::test_secret_bearing_backend_configuration_is_rejected; tests/test_evaluation_reports.py (secret-bearing base_url dropped from report)  
  confidence: `verified`
- **The evaluation snapshot (immutable JSON at creation) records model, backend kind, effective base_url (None for mock), base_seed, temperature, request_timeout_s, seed/timeout provenance labels ('requested' for real backends, 'unavailable'/'not_applicable' for mock), and per-task {task_id, task_version, task_digest}; reports project these and label missing pieces as unavailable.**  
  evidence: afa_api/jobs.py:245-272,388-391; afa_api/evaluation_report.py:112-160,290-350,394-402  
  proven by: tests/test_evaluation_reports.py, tests/test_evaluation_identity.py (not individually re-read line by line)  
  confidence: `read-only-inferred`
- **RunStore.save_run(commit=False) publishes runs+run_scores+diffs+test_results inside a savepoint on the caller's transaction; on any failure every component is rolled back while unrelated pending caller work is preserved; with commit=False nothing is committed. A borrowed connection is never closed by the store.**  
  evidence: runner/afa_runner/store.py:143-274,379-381  
  proven by: tests/test_a2_boundaries.py::test_commit_false_store_seam_does_not_commit_caller_work; tests/test_a3_boundaries.py (SQLite trigger-injected failures at run_scores and after test_results insert, commit/rollback of caller work); runner/tests/test_store.py covers only default-commit save/load/read-only  
  confidence: `verified`
- **RunRecord.run_id is None on any freshly constructed record (including run_once output) and is set to runs.id only by SqliteRunStore.load_runs; save_run ignores a supplied run_id and returns lastrowid.**  
  evidence: runner/afa_runner/pipeline.py:45,152-165; runner/afa_runner/store.py:283,330 and save_run body; probe in scratch copy (run_id=999 input -> stored id 1)  
  proven by: none (no test asserts .run_id on RunRecord)  
  confidence: `verified`
- **runs.task_id = task.id and runs.task_version = task.version of the Task object handed to run_once; in the worker that Task is loaded fresh from tasks/<id> and version+digest are verified equal to the creation snapshot before running, so runs.task_version == evaluation_trials.task_version == snapshot version for worker runs.**  
  evidence: runner/afa_runner/pipeline.py:153-155; afa_api/worker.py:129-142,298,324,360; afa_api/jobs.py:197-217  
  proven by: tests/test_evaluation_identity.py / test_a3_boundaries.py exercise snapshot drift refusal (not re-verified line-by-line here)  
  confidence: `read-only-inferred`
- **Worker persistence of a trial (raw evidence + trial completion + job_runs link) is one commit; a failure rolls back and releases the claim, then fails the job.**  
  evidence: afa_api/worker.py:359-381; afa_api/jobs.py:493-536  
  proven by: tests/test_evaluation_identity.py (injected store wrapper around real store), tests/test_a3_boundaries.py  
  confidence: `read-only-inferred`

### Schema / state facts

- runs table (store.py:49-61): id INTEGER PK AUTOINCREMENT, task_id TEXT NOT NULL, task_version TEXT NOT NULL, agent TEXT NOT NULL, idx INTEGER NOT NULL, status, transcript_hash, duration_ms, created_at DEFAULT datetime('now'), job_id TEXT (nullable). Only index: ix_runs_task_agent(task_id, agent). NO UNIQUE on (task_id, task_version, agent, idx), so repeated fresh evaluations append duplicate positions.
- Sibling raw tables: run_scores (PK run_id+formula_version), diffs (PK run_id, patch_text), test_results; FK enforced via PRAGMA foreign_keys=ON (store.py:~132; a no-op if the borrowed connection is already in a transaction).
- runs has NO provider/base_url/model/temperature/seed columns; provider provenance lives only in evaluation_jobs.snapshot_json / params_json. runs.agent = params.model for all backends (worker.py:315, agent name=model).
- Snapshot JSON schema_version=1 keys: model, backend{kind,base_url}, generation{base_seed,temperature,request_timeout_s,seed_provenance,timeout_provenance}, tasks[{task_id,task_version,task_digest}], repeats (jobs.py:245-272). Reuse compatibility compares model, backend (including base_url), generation, tasks, repeats (jobs.py:288-295).
- evaluation_trials PK (evaluation_id, task_id, idx) with its own task_version and task_digest columns copied from the snapshot (db.py:136-158; jobs.py:411-425); worker links run_id + origin_evaluation_id at completion.
- task_version string = task.json 'version' (currently 1.0.0 / 1.0.1 / 1.0.2 in this branch). jobs.task_snapshot uses str(spec['version']) (jobs.py:210) while load_task uses spec['version'] unconverted (task.py:124); a non-string JSON version would trip the drift check.
- task_digest = sha256 over sorted relative path + bytes of every file under tasks/<id> (jobs.py:185-194); version and digest are re-verified at execution time (worker.py:129-142).
- runs.job_id is written only via save_run(job_id=...) (the worker); CLI examples never set it. db.migrate ALTERs it in for pre-existing DBs (db.py:433-435); SqliteRunStore.__init__ does not migrate.
- Backend verify endpoint probes GET {base}/api/tags for ollama and GET {base}/v1/models for openai_compat with a 5 s httpx timeout (routes_jobs.py:343-378).
- Default request_timeout_s=180, temperature=0.6, base_seed=1000 (schemas.py:82-84); task.timeout_s values in repo are 20/60/120.

### Limitations and suspicious behaviour

- **[low] RunRecord.run_id was inserted before grade_report, so a caller passing grade_report as the 12th POSITIONAL argument now binds it to run_id and leaves grade_report None. The probe reproduced this. Keyword construction and positional construction of the first 11 fields are unaffected. No in-repo caller uses positional 12th arg (all grep hits use keywords).**  
  evidence: runner/afa_runner/pipeline.py:45-49; probe: RunRecord(...,1,'X') -> run_id='X', grade_report=None  
  integration relevance: A merged subsystem that adds fields to RunRecord, or builds RunRecord positionally, can silently mis-bind. Any field ORACLE adds must be keyword-only or placed last.
- **[medium] Stale existing raw DBs: SQLITE_SCHEMA is CREATE TABLE IF NOT EXISTS, so SqliteRunStore(path) never adds runs.job_id to an older DB. save_run(job_id=X) then fails with OperationalError 'no column named job_id' (probe reproduced). Only afa_api.db.migrate adds the column. The job_id=None path uses the old INSERT and works.**  
  evidence: runner/afa_runner/store.py:60,143-200 (two INSERT variants); afa_api/db.py:433-435; probe on old-schema DB  
  integration relevance: Any merge that adds columns to runs (e.g. a task_digest or version-integrity column) must extend db.migrate/_ensure_raw_schema, not just SQLITE_SCHEMA, or the same failure mode recurs on existing DBs.
- **[low] RunStore Protocol not updated: it still declares save_run(record, report=None) while the worker calls save_run(..., commit=False, job_id=...). Any injected/alternate RunStore (e.g. the documented Postgres implementation) that follows the Protocol raises TypeError in the worker. The worker also requires store._conn is conn (worker.py:246), so it is not backend-agnostic.**  
  evidence: runner/afa_runner/store.py:36-44 vs afa_api/worker.py:360-365,246-249  
  integration relevance: A merged store wrapper or subclass must accept commit/job_id kwargs and expose _conn.
- **[medium] Every HTTP error is classified as INFRA_FAILURE (voided), because HTTPError subclasses URLError. A wrong base URL (including one already ending /v1 -> /v1/v1/chat/completions), unknown model (404), bad auth (401; no key can be sent) or server 500 makes every trial voided. The job still ends 'succeeded' if all trials have run rows, and voided runs are excluded from n. Malformed 200 bodies (KeyError, JSONDecodeError, content None) are instead AGENT_ERROR (counted as agent losses).**  
  evidence: runner/afa_runner/agents_ollama.py:33-39,126-141; agents_openai.py:47; worker.py:395-412 (completion requires only completed trials, not non-voided ones)  
  integration relevance: Pass-rate and comparability logic that assumes voided means transient infra can be fooled by a persistent misconfiguration. Not changed by ATLAS, but its report counters surface it only as 'voided'.
- **[medium] Timeout precedence: run_once tests wall-clock > task.timeout_s BEFORE infra_failed, so a slow local model (generation time counts against timeout_s of 20/60/120 s) or a stalled server (request_timeout default 180 s) yields status TIMEOUT (gate fail, counted loss), not a voided infra run. Slow-but-successful output is also scored as TIMEOUT. request_timeout is a per-socket-operation timeout, not a total deadline.**  
  evidence: runner/afa_runner/pipeline.py:106-121; tasks/*/task.json timeout_s; agents_openai.py:45  
  integration relevance: None directly, but it affects any post-merge comparison of model results across versions or timeouts.
- **[medium] Provenance is thin and only 'requested'. The snapshot has no served-model digest, num_ctx, max_tokens or top_p, and no per-trial effective seed or provider. The seed is 'honored by LM Studio / llama.cpp; ignored elsewhere' per the code comment, yet the snapshot labels it 'requested'. The raw runs row has no provider, so the same model name on ollama vs openai_compat collides in runs.agent, which is the key used by legacy aggregate readers (store_load, report_combined).**  
  evidence: afa_api/jobs.py:259-270; agents_openai.py:37; worker.py:315; store.py:49-61  
  integration relevance: Post-merge, per-(agent, task_id, task_version) aggregates cannot distinguish providers. Task-version integrity checks should key on runs.task_version/trial task_digest, not on provider provenance.
- **[low] Execution reads job.params (params_json) while reports read snapshot_json for generation/backend; there is no runtime cross-check that they agree. They are written together at create_job, so they only diverge if a row is edited or schema-defaulted (_job_params_from_row silently falls back to JobParams() defaults on invalid JSON, jobs.py:135-142).**  
  evidence: afa_api/worker.py:315-317; afa_api/jobs.py:100-142,388-391  
  integration relevance: A merged component that rewrites params_json or the snapshot could make the report describe different generation settings than were executed.
- **[low] runs.task_version is written from a freshly loaded Task; the digest/version check (worker.py:133-141) and run_once's copytree of the snapshot dir (pipeline.py:90) are separate steps, so a task file edited in between is a small TOCTOU window; the recorded version can still equal the snapshot while content differs. The trial row also stores the snapshot's version, not the run's, so the raw and trial columns are equal by construction of the check, not by a shared source.**  
  evidence: afa_api/worker.py:129-142,298,324; runner/afa_runner/pipeline.py:90,155  
  integration relevance: HIGH for benchmark-versioning: if a merged subsystem changes what task.version returns (e.g. computed or content-hashed, or the 18 bumped versions) without re-snapshotting, the worker refuses ('changed since evaluation creation') and trials are blocked, rather than silently mixing versions. CLI runs have no such guard.
- **[low] Legacy raw readers re-save loaded records into in-memory stores via save_run(record), which discards record.run_id (new ids assigned), drops grade_report/patch, and loses job_id. Aggregation is keyed by (agent, task_id) with a mixed-version refusal, not by evaluation, so multiple fresh evaluations of the same model stack duplicate idx rows.**  
  evidence: afa_api/store_load.py:142-160; examples/report_combined.py:154; store.py has no uniqueness constraint  
  integration relevance: Nothing uses record.run_id as a key (grep: no non-test use), so it is safe today. A merge that starts keying on RunRecord.run_id would break for the in-memory aggregate stores, where ids differ from disk ids.
- **[info] Borrowed-connection constructor mutates the caller's connection (sets row_factory=sqlite3.Row, issues PRAGMA foreign_keys=ON, which is silently ignored inside an open transaction). With commit=True, save_run also commits any pending caller transaction. save_run with commit=False and no active transaction leaves an explicit BEGIN open.**  
  evidence: runner/afa_runner/store.py:122-134,152-175,270-273  
  integration relevance: Callers other than the worker that share a connection can see row_factory changes or be committed unexpectedly.
- **[info] Docstring/prose claims are not enforced: 'local-only by design' (no host restriction; any http(s) host accepted, and hosted endpoints would 401 -> voided); RunRecord comment says run_id 'never replaces task/index keys' (true, and it is unused). The Settings URL/backend defaults (ollama_base_url, openai_base_url, default_backend) are persisted but never consulted when creating or running jobs.**  
  evidence: afa_api/schemas.py:39-66,153-178; grep for settings usage found none in jobs/worker  
  integration relevance: none

### Integration assumptions

- tasks/<task_id>/task.json exists with string 'id' equal to the directory name and a string 'version'; the task pack is a directory under ROOT/tasks hashed recursively (rglob of every file, including junk like .DS_Store) for task_digest, so any file change in a task dir changes the digest and blocks trials for evaluations created earlier.
- task.version (the runner's Task.version from task.json['version']) is the single source of runs.task_version; a versioning merge that changes how Task.version is derived changes what gets written to runs.task_version, and the worker only accepts it if it still equals the snapshot's task_version.
- The worker assumes the API control-plane DB and the raw runs tables are the same SQLite file/connection (borrowed connection, single-commit boundary) and that db.migrate has run so runs.job_id exists.
- runs has no uniqueness on (task_id, task_version, agent, idx); evaluation scoping depends entirely on evaluation_trials.run_id links and job_runs, not on runs columns.
- RunRecord field order is load-bearing for positional callers; the new field run_id sits between duration_ms and grade_report.
- Backend kinds are closed to exactly mock/ollama/openai_compat in schemas.py, evaluation_report.py (_REPORT_BACKEND_KINDS) and worker.factory_for; a new provider needs edits in all three (plus DEFAULT_BACKEND_URLS/verify).
- openai_compat base_url must NOT include /v1 (the client appends /v1/chat/completions).
- Agents that support deterministic resume must implement set_run_seed (duck-typed via getattr); others silently ignore seed control.

### Open questions

- Does any code outside the audited files (routes_readonly/serialize/projection) read runs.job_id vs job_runs vs evaluation_trials.run_id, and could they disagree for reused evidence? Not audited here.
- Are the default OllamaAgent options (no num_ctx, no max_tokens) an intentional evaluation contract? They are unchanged from master and not recorded in the snapshot.
- Is `tests/test_evaluation_identity.py`'s injected-store wrapper (line ~113-119) faithful enough to prove the worker's atomicity claim, or does only test_a3_boundaries prove it? Read only at the excerpt level.
- How will ORACLE-bumped task versions interact with previously created ATLAS evaluations' snapshots (they would be refused as drifted on resume) and with reuse (source trial task_version vs new version)? That belongs to the merge audit, not to this subsystem.

---

## ATLAS worker ownership, fencing, trial claims, stale-worker recovery, duplicate prevention, restart, execution path (frozen 1e1a788)

**Ownership model.** Two layers. (1) DB fencing token: `evaluation_jobs.owner_token` plus `owner_started_at` (a diagnostic lease). `claim_job_token` (jobs.py:692-704) does `UPDATE ... SET status='running', owner_token=? WHERE id=? AND status='queued' AND owner_token IS NULL`. Exactly one caller wins. The token is passed explicitly to `run_job`; the worker never re-reads it to adopt (worker.py:190-210). (2) A same-host OS lock: `flock(LOCK_EX|LOCK_NB)` on `$TMPDIR/agentforge-arena-evaluation-locks/<sha(dbpath)>/<sha(evaluation_id)>.lock`, plus an in-process set (jobs.py:42-100). `run_job` takes the lock AFTER the queued->running commit, then re-checks that the token still matches. Trial claims use `evaluation_trials.trial_state` (pending/claimed/completed/blocked) plus `claim_token`. Claim is `UPDATE ... WHERE trial_state='pending' AND EXISTS(job running AND owner_token=?)` (jobs.py:472-490).

**Stale.** Liveness is decided by the OS lock, not the lease. `reclaim_stale_running` skips any job whose lock is held. If the lock is free, it reclaims when `recover_unlocked=True` (startup, worker `serve`) regardless of lease age. With `recover_unlocked=False` (resume) it reclaims only if the lease is older than max(300s, request_timeout+60). Reclaim resets the job to queued, clears the owner, and resets ALL `claimed` trials to pending (jobs.py:749-833). `touch_owner` renews the lease only once per trial, before execution (worker.py:273), never during model or grading calls.

**Fencing.** `complete_trial` (jobs.py:507-528) runs `UPDATE evaluation_trials SET trial_state='completed',... WHERE ... AND trial_state='claimed' AND claim_token=? AND EXISTS(SELECT 1 FROM evaluation_jobs WHERE id=? AND status='running' AND owner_token=?)`. It raises `TrialClaimError` on rowcount != 1. It runs in the SAME uncommitted transaction as `store.save_run(commit=False)` on the one borrowed connection (worker.py:360-377), so it is atomic. SQLite's write lock is taken at the first raw INSERT, and the fence is then checked under that lock. Probe (copy of the tree): the job was taken over mid-`act()`. Result: raw run/score/diff/test/job_runs counts unchanged and the successor's claim intact. `mark_terminal(owner_token=)` and `touch_owner` are also fenced. `append_event` is NOT fenced (see limitations).

**Restart.** Startup (main.py:51-69) runs migrate, then `reclaim_stale_running(recover_unlocked=True)`, then auto-dispatches every recovered job. That is automatic same-ID resume; no explicit resume is needed. Completed trials are kept and skipped (`run_skipped`). The interrupted in-flight trial is re-executed, because nothing partial was committed. Failed and canceled jobs are NOT auto-resumed; they need `POST /jobs/{id}/resume` (jobs.py:836-873). That call re-validates task drift, refuses a live owner, and reopens blocked trials. Between a kill and the next startup, status stays `running`.

**Duplicates.** `evaluation_trials` PK is (evaluation_id, task_id, idx). `runs` has no uniqueness, so duplicate raw rows are prevented only by the claim/complete state machine, the owner token and the lock. A double dispatch loses at the conditional claim or at the lock.

**Execution path.** `jobs.trial_rows` gives the positions. Per trial: `touch_owner`; completed trials are skipped and blocked ones ignored; the cancel check runs; `_load_snapshot_task` (worker.py:129-142) loads `TASKS_DIR/<id>` via `afa.load_task` and compares `task.version` and the full-directory sha256 (`jobs.task_snapshot`, jobs.py:185-217) to the evaluation snapshot. On drift it calls `mark_trial_unverifiable`, which blocks every non-completed position for that task, and the loop continues. Then `claim_trial`, `agent_factory(model, task, params)` (mock/ollama/openai_compat; agents cached per task), `set_run_seed(base_seed+idx)`, `afa.run_once`, and the atomic save/complete/commit. Backend, model and seed come from `job.params`, not from the snapshot.

**Cancel/failure.** Cancel is checked only between trials, and again after the loop. Any exception in a trial rolls back, releases the claim to pending, and fails the whole job (`job_failed` event with traceback). No error evidence row exists for the trial. Agent exceptions inside `run_once` become AGENT_ERROR runs, which are persisted normally.

**Tests.** test_a3_boundaries uses real sqlite files and real threads with Events. Two tests spawn real subprocesses and kill them (`standalone_process_restart`, `registered_api_lifespan_dispatches_interrupted_trial`). It uses no fake clocks; leases are aged by SQL `UPDATE`. It uses a mock agent, and `run_once` is real.

### Guarantees (claim / evidence / proven-by / confidence)

- **Only one caller can move an evaluation queued->running and obtain the owner_token; the token is threaded explicitly and a delayed dispatcher whose token no longer matches returns without executing.**  
  evidence: afa_api/jobs.py:692-704; afa_api/worker.py:187-210,454-470  
  proven by: tests/test_evaluation_identity.py::test_competing_connections_have_one_evaluation_owner (2 threads, real sqlite, claim_job only); test_a3_boundaries::test_reclaim_race_does_not_leave_dirty_connection_or_touch_successor  
  confidence: `verified`
- **A stale/replaced worker cannot publish a run over a successor. Raw run+score+diff+tests, the trial completion and the job_runs link commit in one transaction, and complete_trial's UPDATE is guarded by claim_token AND job running AND owner_token in that same transaction; any mismatch raises TrialClaimError and the worker rolls back everything. Probed empirically: DB-level takeover during act() left raw counts unchanged and the successor's claimed row intact.**  
  evidence: afa_api/worker.py:360-381; afa_api/jobs.py:493-536; runner/afa_runner/store.py:143-270 (SAVEPOINT inside caller txn, commit=False)  
  proven by: test_evaluation_identity::test_stale_owner_cannot_complete_successor_claim proves ONLY the SQL guard by direct complete_trial call (no save_run, no concurrency). test_a3_boundaries::test_worker_association_failure_rolls_back_all_evidence_components and ::test_worker_failure_rolls_back_raw_score_diff_test_link_and_trial prove transactional rollback via injected failures. No repo test drives a full stale-worker takeover through run_job (only my probe did).  
  confidence: `verified`
- **mark_terminal(owner_token=...) and touch_owner are fenced, so a stale worker cannot finish, fail or cancel a successor's evaluation.**  
  evidence: afa_api/jobs.py:721-729,926-933; worker.py:273-274  
  proven by: test_a3_boundaries::test_standalone_process_restart_preserves_completed_trial_and_cancel_state (old token mark_terminal on succeeded job is a no-op)  
  confidence: `verified`
- **A killed process does not lose committed trials; on restart, running jobs whose OS lock is free are requeued, claimed trials reset to pending, completed trials are skipped, and only the missing position re-executes under a new token. Startup auto-dispatches these.**  
  evidence: afa_api/main.py:51-69; jobs.py:749-833; worker.py:275-289  
  proven by: test_a3_boundaries::test_registered_api_lifespan_dispatches_an_interrupted_trial (real subprocess SIGKILL, real lifespan) and ::test_standalone_process_restart_preserves_completed_trial_and_cancel_state  
  confidence: `verified`
- **A live same-host owner is never reclaimed because of lease age; the flock is the liveness signal.**  
  evidence: jobs.py:749-770; jobs.py:83-100  
  proven by: test_standalone_process_restart... (cross-process, lease aged -1h, competitor does not steal). test_registered_api_dispatch_and_startup_protect_an_aged_owner is same-process so the in-process set, not flock, does the work. test_evaluation_identity::test_live_owner_is_not_reclaimed_but_stale_owner_is is misnamed: no lock is held, the job is protected only by a fresh lease with recover_unlocked=False.  
  confidence: `verified`
- **Task drift is re-validated per trial before execution against snapshot version and full-directory sha256; drift blocks the task's uncompleted positions (never executes them), fails the job, and explicit resume re-opens blocked positions only after the snapshot revalidates.**  
  evidence: worker.py:129-142,297-306; jobs.py:185-236,539-558,836-873  
  proven by: test_evaluation_identity::test_changed_task_snapshot_is_unverifiable_not_drifted (stubs jobs.task_snapshot digest); test_a3_boundaries::test_restored_snapshot_resume_reopens_only_blocked_positions (real file mutation of task.json during trial 1)  
  confidence: `verified`
- **Cancellation is cooperative between trials: an in-flight trial finishes and is persisted before the job becomes canceled; queued jobs cancel immediately; cancel_requested survives restart and only explicit resume clears it.**  
  evidence: worker.py:292-295,391-394; jobs.py:876-893,851-857  
  proven by: test_a3_boundaries::test_standalone_process_restart... ; test_cancel_claim_race_flags_the_actual_running_state; tests/test_jobs_api.py::test_cancel_running_job_is_honored_between_runs  
  confidence: `verified`
- **On a trial exception nothing partial is persisted and the claim is released to pending; the job is failed with error_message and traceback event. Committed trials survive and are not re-executed on resume, even if the post-commit event write failed.**  
  evidence: worker.py:312-322,378-381,413-424  
  proven by: test_a3_boundaries::test_post_commit_event_failure_preserves_all_evidence_through_resume; test_evaluation_identity::test_resume_keeps_committed_trial_and_runs_only_pending (stubs run_once to raise on call 2)  
  confidence: `verified`

### Schema / state facts

- evaluation_jobs columns: id PK, status (queued|running|succeeded|failed|canceled), cancel_requested, params_json, total/completed/passed/voided/failed/reused_runs, mode (fresh|reuse|legacy default), source_evaluation_id, snapshot_json, owner_token, owner_started_at, created_at, started_at, finished_at, error_message (db.py:86-105). Job pydantic model does not expose owner_token/owner_started_at.
- evaluation_trials: PK (evaluation_id, task_id, idx); trial_state pending|claimed|completed|blocked; evidence_state missing|fresh|reused|unverifiable; run_id FK runs(id); source_/origin_evaluation_id, source_run_id, claim_token, claimed_at, completed_at, error_message, task_version, task_digest (db.py:136-152).
- job_runs PK (job_id, run_id): compat link, INSERT OR IGNORE on completion (jobs.py:533-536). runs has NO uniqueness beyond autoincrement id; runs.job_id = origin evaluation, written in the same txn (store.py:187-201).
- job_events UNIQUE(job_id, seq); seq = SELECT MAX(seq)+1 then INSERT, per-call commit (jobs.py:974-993).
- Lock file: tempfile.gettempdir()/agentforge-arena-evaluation-locks/<sha256(resolved db path)[:24]>/<sha256(evaluation_id)>.lock, never deleted; memory DB keyed by id(conn).
- Connection: sqlite3 default legacy isolation, WAL, foreign_keys=ON, busy_timeout=5000ms (db.py:77,161-166).
- Event vocabulary: job_started, run_started, run_diff, run_graded, run_scored, run_persisted, run_skipped, progress, error, job_failed, job_done, job_canceled, job_reclaimed, job_resumed.
- Endpoints: POST /jobs (auto-dispatch thread), /jobs/{id}/cancel, /retry (new fresh job), /resume (same id), GET /jobs/{id}/trials|results|report.json|report.md, /events (SSE or ?since=). Counters are derived from committed trials via refresh_counters (jobs.py:561-588).
- Worker entry points: dispatch_job (daemon thread, own connection, db.migrate then claim_job_token then run_job), claim_and_run (poller), serve() (startup reclaim then poll loop).

### Limitations and suspicious behaviour

- **[high] Corrupt or invalid params_json silently degrades to default JobParams (mock backend, model='mock'); the worker uses job.params, never the snapshot, so a non-legacy job with unparseable params would run the reference-solution MockAgent and persist 'fresh' comparable evidence under a job whose snapshot names a different model/backend. Probed: params_json='{corrupt' on an ollama/real-model-x job -> agent 'mock', status valid, passed 1/1, job succeeded.**  
  evidence: jobs.py:112-138 (_job_params_from_row returns JobParams() on error); worker.py:236-237,315-317 use job.params; probe2.py output  
  integration relevance: Any merge that changes params_json shape or adds fields could trigger the silent fallback and produce perfect-score mock evidence; there is no cross-check of snapshot vs params.
- **[medium] Mock backend produces perfect scores from the task's reference solution but labels runs agent=<model string>; runs table has no backend/provenance column. Only evaluation_jobs.snapshot_json records backend.kind.**  
  evidence: worker.py:41-58 (writes from task.reference_dir), afa.MockAgent(name=model); store.py runs DDL  
  integration relevance: Raw runs from mock evaluations are indistinguishable in the runs table; an integrity engine reading runs alone cannot separate them from real model runs.
- **[medium] Infrastructure failures are 'completed'. Model server unreachable -> INFRA_FAILURE voided run, persisted as trial_state='completed', evidence_state='fresh'; the job ends 'succeeded'. Probed: 2 infra-failed trials -> job succeeded, voided_runs=2, passed=0.**  
  evidence: pipeline.py:113-115 (run_once); worker.py:395-412 (all_trials_completed only checks trial_state); jobs.py:591-597; probe1.py  
  integration relevance: 'succeeded' does not imply usable evidence; consumers must consult voided counts.
- **[medium] job_events writes are not fenced. A stale worker that lost ownership still appends run_diff/run_graded/run_scored and a job_failed event (with its traceback) to the successor's event stream, although its evidence and terminal transition are correctly rejected. Probed: successor's job remained running; stale worker's events (seq 3-6) appeared in it.**  
  evidence: jobs.py:974-993 (no owner predicate); worker.py:318-358,413-421; probe1.py event list  
  integration relevance: Event log is not authoritative evidence. Note run_diff/run_graded/run_scored events are emitted and committed BEFORE the raw save, so they can exist for a run that was never persisted.
- **[low] Cancel requested during the final trial converts the job to 'canceled' even though every trial completed (the post-loop cancel check runs before the completeness check).**  
  evidence: worker.py:391-394; probe2.py: canceled with completed_runs=1/1  
  integration relevance: none
- **[medium] Task drift is checked before each trial but not after. The run_once executes against the live tasks/ directory, so a mutation during the trial (test does exactly this) still yields a 'fresh' completed trial whose evidence was graded against changed content. Digest and load_task are two separate reads (TOCTOU). Also cached agent per task keeps state derived from the first load.**  
  evidence: worker.py:297-324,313-316; test_a3_boundaries.py:278-350 (drift written during act, trial 1 still completed)  
  integration relevance: After merge, anything that changes task files or versions mid-evaluation (e.g. bumped task versions) makes running/resumable evaluations refuse via drift, and reuse sources become incompatible (_snapshot_identity includes task_version+digest, jobs.py:288-295).
- **[medium] Task digest hashes EVERY file under tasks/<id> (rglob, incl. .DS_Store, __pycache__, any new integrity manifest files), and version comes from task.json. Any added/generated file changes the digest and blocks in-flight or resumable evaluations.**  
  evidence: jobs.py:185-217  
  integration relevance: A merged integrity subsystem adding files/metadata inside task dirs, or bumping version in task.json, will invalidate all pre-existing snapshots (resume -> JobStateError, worker -> blocked trials).
- **[medium] Liveness relies on a same-host flock in tempfile.gettempdir(). Different TMPDIR, different host, container or NFS share means the lock is invisible; startup recover_unlocked=True would then requeue a live foreign worker. DB-token fencing still protects evidence, but work is wasted and the foreign worker's job_failed events pollute the log. Lease is not heartbeated during model calls, so it is useless as liveness.**  
  evidence: jobs.py:72-100,749-833; worker.py:273  
  integration relevance: Assumes single host and single TMPDIR for API + workers.
- **[low] Window between queued->running commit and lock acquisition: another process's startup reclaim (recover_unlocked=True) can requeue the just-claimed job. Dispatcher bails on token mismatch (benign, but the job is re-dispatched by whoever reclaimed).**  
  evidence: worker.py:462-464,195-201; jobs.py:786-801  
  integration relevance: none
- **[low] append_event uses SELECT MAX(seq)+1 then INSERT with UNIQUE(job_id,seq) in autocommit; two writers on the same job (stale + successor, or API resume) can raise IntegrityError, which in the worker loop fails the job.**  
  evidence: jobs.py:982-993  
  integration relevance: none
- **[low] Any single-trial exception fails the whole evaluation (remaining trials stay pending, no per-trial error evidence, only job.error_message and a job_failed event with traceback). Post-commit event failure also fails the job even though evidence is committed. Blocked-trial path loops with stale row state and emits repeated error events.**  
  evidence: worker.py:378-381,383-389,413-424,297-306  
  integration relevance: none
- **[info] Dead/compat code: _completed_indices and _conn_db_path are defined but unused in worker.py; bump_counters, claim_job, claim_next_queued are compat wrappers. Docstring says 'reclaim only if lease stale' but recover_unlocked bypasses lease entirely.**  
  evidence: worker.py:94-113; jobs.py:707-711,938-955,749-756  
  integration relevance: none
- **[low] Daemon dispatch threads die with the API process leaving status 'running' with no liveness indicator until next startup; resume_job refuses ('owned by live worker') until the lease ages past 300s or request_timeout+60 even if the lock is free.**  
  evidence: worker.py:468; jobs.py:847-850,786-787  
  integration relevance: none

### Integration assumptions

- tasks/<task_id>/ exists with task.json containing string keys 'id' (== directory name) and 'version'; afa.load_task(TASKS_DIR/<id>) returns a Task with .version, .snapshot_dir, .reference_dir, .protected_paths, .editable_paths, .timeout_s. TASKS_DIR (worker.py:29) and db.ROOT/'tasks' (jobs.py:199) are two separate path sources that must agree.
- Task identity is (task_id, task.json version, sha256 of every file in the task dir). ORACLE version bumps or added files will change this and invalidate existing snapshots, resumes and reuse sources.
- Runner API surface used: afa.run_once(agent, task, sandbox=, idx=) -> RunRecord with .grade_report/.score/.status/.files_changed etc; afa.SqliteRunStore(connection=conn).save_run(rec, report=, commit=False, job_id=) with SAVEPOINT semantics; afa.LocalSandbox; afa.MockAgent/OllamaAgent/OpenAICompatAgent; optional agent.set_run_seed. These runner changes (store.py connection/commit/job_id, RunRecord.run_id) are ATLAS-side edits of a 'frozen' package; ORACLE must not diverge save_run's signature or insert columns.
- Raw tables runs/run_scores/diffs/test_results exist with the frozen column set; runs.job_id is added by db.migrate; save_run writes runs.job_id at insert. Any ORACLE added NOT NULL column or trigger on runs would break the single-transaction insert and, by rollback, fail every trial.
- Single host, single process-tree TMPDIR, single sqlite file with WAL; ownership uses OS flock plus DB token; no cross-host coordination.
- Worker uses job.params (model/backend/seed/temperature), not snapshot_json, to build agents; params_json and snapshot_json are assumed consistent.
- complete_trial and claim_trial assume evaluation_jobs.status/owner_token are the fencing source; an integrity subsystem that also updates evaluation_jobs status or owner columns, or reclaims trials, must preserve the AND-owner_token predicate.
- Completion truth is evaluation_trials.trial_state='completed' with a non-NULL run_id; events and counters are derived projections that may lag.

### Open questions

- Does any code (evaluation_report/projection) filter or annotate mock-backend evaluations, given runs carries no backend column?
- Are task dirs guaranteed free of generated files (__pycache__, .DS_Store) in normal operation, or does the drift digest trip on benign files?
- Is a multi-process deployment (API process + standalone worker on different TMPDIRs) expected? If so lock-based recovery assumptions break.
- I did not empirically test true concurrent thread interleaving of two writers at the exact save_run boundary; atomicity is inferred from SQLite write-lock semantics plus the takeover probe, not from a stress test.

---

## ATLAS durable evaluation identity, trial identity, fresh/resume/reuse semantics, task snapshots/digest/drift, provenance, transaction boundaries (afa_api/jobs.py, worker.py, routes_jobs.py, schemas.py, db.py)

**Identity hierarchy.** `evaluation_jobs.id` is `uuid.uuid4().hex`, random and not derived from parameters (jobs.py:311). Each requested position is one `evaluation_trials` row with PK (evaluation_id, task_id, idx), created eagerly for tasks x repeats inside the create transaction (jobs.py:402-431). `evaluation_trials.run_id` is a nullable FK to `runs.id`. Raw `runs` keeps non-unique (task_id, task_version, agent, idx) columns, so nothing forces global uniqueness and repeated evaluations legitimately produce duplicate tuples. `runs.job_id` records the origin evaluation. `job_runs(job_id, run_id)` is a compatibility link with no FKs.

**FRESH (default).** `mode` defaults to "fresh" (schemas.py:85). A new job gets new pending trials. The only code that pre-completes trials is the `mode=='reuse'` branch (jobs.py:395-431). The worker executes every non-completed trial via `run_once` and inserts a new `runs` row with AUTOINCREMENT id (worker.py:324-376, store.py:171-200). The old global "already have a run" lookup `_completed_indices` (worker.py:105) is dead code and nothing calls it. `retry_job` clones params into a new fresh job.

**RESUME.** `resume_job` (jobs.py:836-873) keeps the same evaluation ID. It validates every snapshot task, requires status failed, canceled or queued, and resets blocked/unverifiable trials to pending. Completed trials are untouched, so their run IDs are kept. The worker loop skips completed trials with a `run_skipped` event (worker.py:275-289). Startup also auto-recovers any running job whose owner lock is free, via `reclaim_stale_running(recover_unlocked=True)`, and re-dispatches it (main.py:48-70).

**REUSE.** Opt-in (`mode=reuse` plus `source_evaluation_id`). It is an all-or-nothing clone: the source must have exactly the requested (task, idx) set, every trial completed with evidence fresh or reused, and score, diff and at least one test_result rows present. Nothing executes, and no new `runs` rows are created. Compatibility is `_snapshot_identity` equality (jobs.py:288-295, 323), meaning model, backend {kind, effective base_url}, generation {base_seed, temperature, request_timeout_s, provenance}, the ORDERED task list of {task_id, task_version, task_digest}, and repeats. The target snapshot is computed from CURRENT task files, so a task changed since the source ran makes reuse "incompatible". Origin is read from `runs.job_id` (jobs.py:357-375). Chained reuse is allowed: source_evaluation_id is the immediate source and origin_evaluation_id is the original creator.

**Snapshot and drift.** Digest is sha256 over every file under tasks/<id>/ (relative path, NUL, bytes, NUL). It is checked in three places. At create it is simply computed. At resume, `validate_snapshot_tasks` raises JobStateError (HTTP 409) before any state change. At worker time, `_load_snapshot_task` runs before each non-completed trial, and on mismatch the trials are blocked/unverifiable and the job ends failed. Nothing is checked at dispatch or claim, or for already-completed trials. The check is not held during a trial.

**Transactions.** Atomic units:
- create_job (job, trials and job_runs)
- save_run(commit=False) plus complete_trial plus the job_runs insert, committed once (worker.py:359-377)
- the reclaim savepoint
- the resume UPDATEs

Events, counters and claim_trial commit separately.

### Guarantees (claim / evidence / proven-by / confidence)

- **Evaluation ID is random uuid4 hex, not derived from params; two identical requests always yield distinct evaluation IDs and distinct trial rows.**  
  evidence: afa_api/jobs.py:311; evaluation_jobs.id TEXT PRIMARY KEY afa_api/db.py:87  
  proven by: tests/test_evaluation_identity.py::test_default_evaluations_are_fresh_and_raw_ids_are_distinct (mock backend, calls worker.run_job directly)  
  confidence: `verified`
- **FRESH mode re-executes every position and inserts new raw runs rows; no code path pre-completes a trial except explicit reuse; raw runs has no UNIQUE constraint on (task,version,agent,idx).**  
  evidence: jobs.py:395-431 (only reuse sets trial_state=completed); worker.py:270-376; runner/afa_runner/store.py:50-60 (runs schema) and :171-200; worker._completed_indices unused (worker.py:105)  
  proven by: test_evaluation_identity.py::test_default_evaluations_are_fresh_and_raw_ids_are_distinct; tests/test_jobs_api.py::test_same_parameters_are_fresh_and_not_reused  
  confidence: `verified`
- **mode/source_evaluation_id are cross-validated at build_snapshot: reuse without source and fresh with source both raise JobStateError; JobCreate forbids extra fields; resume is not a create flag.**  
  evidence: jobs.py:246-249; schemas.py:89-93,85-86; routes_jobs.py:89-90 maps JobStateError to HTTP 409  
  proven by: none directly for the two mode/source mismatch messages  
  confidence: `read-only-inferred`
- **Resume keeps the same evaluation ID and completed trials' run_ids; only pending (and previously blocked/unverifiable then reset) positions execute; already-committed trial is skipped even if post-commit events failed.**  
  evidence: jobs.py:836-873; worker.py:275-289; trials.run_id preserved because complete_trial only targets trial_state='claimed' rows (jobs.py:507-513)  
  proven by: test_evaluation_identity.py::test_resume_keeps_committed_trial_and_runs_only_pending (interruption simulated by monkeypatching afa.run_once to raise on call 2), ::test_post_commit_event_failure_recovers_without_duplicate_raw_run (monkeypatches jobs.append_event), tests/test_a2_boundaries.py::test_http_resume_preserves_completed_evidence_and_id, tests/test_a3_boundaries.py::test_restored_snapshot_resume_reopens_only_blocked_positions (real task.json mutation)  
  confidence: `verified`
- **Resume fails closed on real task-pack drift: any snapshot task whose version or digest differs (or is missing) raises JobStateError BEFORE any status/trial mutation (job stays canceled/failed).**  
  evidence: jobs.py:844 (validate_snapshot_tasks) precedes UPDATE at :851; validate at :220-236; route returns 409 at routes_jobs.py:167-168  
  proven by: tests/test_a2_boundaries.py::test_resume_rejects_real_task_pack_drift (copies task dir, edits task.json version on disk)  
  confidence: `verified`
- **Worker refuses to execute a not-yet-completed position whose task version/digest differs from the snapshot: the task's non-completed trials become trial_state='blocked', evidence_state='unverifiable'; the job ends 'failed' with 'no verifiable evidence'; no raw run is written.**  
  evidence: worker.py:129-142,297-306,396-410; jobs.py:539-558  
  proven by: test_evaluation_identity.py::test_changed_task_snapshot_is_unverifiable_not_drifted (STUBS jobs.task_snapshot to return a fake digest, not a real file change); test_a3_boundaries.py::test_restored_snapshot_resume_reopens_only_blocked_positions (real file mutation)  
  confidence: `verified`
- **Reuse compatibility predicate is exact equality of snapshot identity {model, backend{kind,effective base_url}, generation{base_seed,temperature,request_timeout_s,seed_provenance,timeout_provenance}, ordered tasks[{task_id,task_version,task_digest}], repeats}; mismatch raises JobStateError 'reuse source snapshot is incompatible' (HTTP 409) and no rows are inserted (rollback).**  
  evidence: jobs.py:288-295,323-324,437-440; snapshot built at :256-272  
  proven by: tests/test_a3_boundaries.py::test_reuse_rejects_each_incompatible_snapshot_identity_atomically (model, backend, generation, task_version, task_digest; the task_* cases mutate the SOURCE's stored snapshot_json)  
  confidence: `verified`
- **Reuse additionally fails closed when the source is missing/legacy/has no snapshot, has a different (task,idx) set, has any non-completed trial, evidence_state not in (fresh,reused), null run_id, missing run_scores/diffs/patch_text or zero test_results, null runs.job_id, or an origin job that is missing/legacy. Each is a JobStateError with a distinct message ('unavailable or legacy', 'missing or incomplete trials', 'unknown or unverifiable evidence/origin', 'unverifiable').**  
  evidence: jobs.py:319-375  
  proven by: test_a3_boundaries.py::test_reuse_rejection_covers_incompatible_task_identity_and_unverifiable_evidence, ::test_reuse_rejects_new_eligibility_gates_without_logical_changes, ::test_reuse_rejects_legacy_source_without_creating_any_rows; test_a2_boundaries.py::test_reuse_rejection_is_all_or_nothing  
  confidence: `verified`
- **Reused trials are stored completed with evidence_state='reused', run_id=source run, source_evaluation_id=immediate source, source_run_id, origin_evaluation_id=runs.job_id of the raw row; no new runs rows; job created with completed_runs=reused_runs=total; trial_detail labels comparability 'provisional' for reused vs 'comparable' for fresh (only when patch+tests present).**  
  evidence: jobs.py:377-436, 660-666  
  proven by: test_evaluation_identity.py::test_explicit_reuse_has_source_and_origin_without_new_raw_rows; test_a3_boundaries.py::test_reuse_chain_keeps_immediate_source_and_original_origin_without_execution  
  confidence: `verified`
- **Task digest = sha256 over sorted rglob('*') of files under tasks/<id>/ (relative posix path + NUL + raw bytes + NUL), covering task.json, snapshot/, grading/, reference/, and any stray file; task_version comes from task.json 'version' and task_id must equal spec 'id'. Stored in evaluation_jobs.snapshot_json and copied per trial into evaluation_trials.task_version/task_digest.**  
  evidence: jobs.py:185-217,255-272,402-431  
  proven by: tests/test_evaluation_reports.py asserts digest startswith 'sha256:'; no test hashes a directory containing junk files  
  confidence: `verified`
- **Raw run rows, score, diff, test_results, trial completion and job_runs link commit atomically; any failure before commit rolls all back and releases the claim to pending; a stale owner cannot complete a successor's claim (fenced by claim_token and owner_token).**  
  evidence: worker.py:359-381; jobs.py:493-536; store.py:143-275 (savepoint, commit=False)  
  proven by: test_evaluation_identity.py::test_raw_trial_transaction_rolls_back_together (wraps real save_run then raises, so simulates association failure, not a real complete_trial failure); ::test_stale_owner_cannot_complete_successor_claim; test_a3_boundaries.py::test_worker_association_failure_rolls_back_all_evidence_components  
  confidence: `verified`
- **create_job writes the job, all trial rows and (for reuse) job_runs in one transaction with rollback on any exception; commit only at the end.**  
  evidence: jobs.py:315-440  
  proven by: test_a3_boundaries.py reuse-rejection tests assert logical rows unchanged after failure  
  confidence: `verified`
- **Single running owner per evaluation is enforced by an atomic conditional UPDATE (status='queued' AND owner_token IS NULL) plus a same-host flock; live owners are not reclaimed merely because the lease aged.**  
  evidence: jobs.py:42-100,692-704,749-833  
  proven by: test_evaluation_identity.py::test_competing_connections_have_one_evaluation_owner; test_a2_boundaries.py::test_live_owner_lock_protects_and_startup_recovers_before_lease_expiry  
  confidence: `verified`

### Schema / state facts

- evaluation_jobs(id TEXT PK, status TEXT NOT NULL, cancel_requested INT, params_json TEXT NOT NULL, total_runs, completed_runs, passed_runs, voided_runs, failed_runs, reused_runs, mode TEXT NOT NULL DEFAULT 'legacy', source_evaluation_id TEXT, snapshot_json TEXT, owner_token TEXT, owner_started_at TEXT, created_at, started_at, finished_at, error_message). No CHECK on status/mode (db.py:86-106). Status Literal: queued|running|succeeded|failed|canceled (schemas.py:21); mode: fresh|reuse|legacy (ALTER-added rows default 'legacy').
- evaluation_trials(evaluation_id TEXT NOT NULL REFERENCES evaluation_jobs(id), task_id, idx INT, task_version TEXT NOT NULL, task_digest TEXT NOT NULL, trial_state DEFAULT 'pending', evidence_state DEFAULT 'missing', run_id INT REFERENCES runs(id), source_evaluation_id, source_run_id, origin_evaluation_id, claim_token, claimed_at, completed_at, error_message, PRIMARY KEY(evaluation_id,task_id,idx)); indexes on run_id and (evaluation_id,trial_state) (db.py:136-157). No CHECKs; source_/origin_evaluation_id and source_run_id have NO FK. run_id is NOT unique (reused trials share source run_id).
- trial_state values used in code: pending | claimed | completed | blocked. evidence_state: missing | fresh | reused | unverifiable. trial_detail also emits artifact_state absent|unavailable|partial|complete and comparability provisional|comparable (only when artifacts complete).
- job_runs(job_id TEXT, run_id INT, PRIMARY KEY(job_id,run_id)) - no FKs; reused runs are ALSO linked here, so run_ids_for_job(reuse job) returns the source's run ids while runs.job_id keeps the origin.
- job_events(id AUTOINCREMENT, job_id FK, seq, UNIQUE(job_id,seq)); seq = MAX(seq)+1 read-then-insert (jobs.py:982-989), not atomic across connections.
- runs(id INTEGER PK AUTOINCREMENT, task_id, task_version, agent, idx, status, transcript_hash, duration_ms, created_at, job_id TEXT NULL) - job_id ALTER-added, no FK, no unique on (task,version,agent,idx) (runner store.py:50-60; db.py:433-435). run_scores PK (run_id, formula_version); diffs PK run_id; test_results(id, run_id,...).
- snapshot_json shape: {schema_version:1, model, backend{kind,base_url(effective; None for mock)}, generation{base_seed,temperature,request_timeout_s,seed_provenance('unavailable' for mock else 'requested'),timeout_provenance('not_applicable' for mock else 'requested')}, tasks[{task_id,task_version,task_digest 'sha256:...'}], repeats} (jobs.py:256-272). `name` and mode are NOT in the identity.
- Endpoints: POST /api/v1/jobs (409 JobStateError, 503 RuntimeError/migration refusal, 422 ValueError/sqlite3.Error), POST /jobs/{id}/resume (409 JobStateError e.g. 'owned by a live worker', 'succeeded evaluations are not resumable', 'changed since evaluation creation'), POST /jobs/{id}/retry (new FRESH job; 409 if not terminal/legacy), GET /jobs/{id}/trials|results|trials/{task}/{idx}|report.json|report.md, GET /runs/{run_id} exact, GET /run/{agent}/{task}/{idx} -> 409 with candidate_run_ids when ambiguous (routes_jobs.py; routes_readonly.py:98-118; serialize.py:308-311).
- Worker event order per trial: run_started, run_diff, run_graded, run_scored (all committed BEFORE persistence), then save_run+complete_trial commit, then run_persisted, progress (refresh_counters). Counters (completed/passed/voided/failed/reused) are derived from committed trials LEFT JOIN run_scores; passed/voided/failed count only evidence_state='fresh'.
- Locking: fcntl.flock on {tempfile.gettempdir()}/agentforge-arena-evaluation-locks/<sha256(dbpath)[:24]>/<sha256(evaluation_id)>.lock plus in-process set (jobs.py:42-100). Stale lease threshold = max(300s, request_timeout_s+60s) (jobs.py:780).
- db.migrate: refuses evidence DB path, refuses to run with an open caller transaction, validates existing app-table columns and unconditional unique identity keys, never drops; sets WAL, foreign_keys=ON, busy_timeout=5000 per connection (db.py:161-166,391-453).
- Tasks root is db.ROOT/'tasks' for jobs.task_snapshot (jobs.py:199) and worker.TASKS_DIR = ROOT/'tasks' for afa.load_task (worker.py:29,133); tests monkeypatch both.

### Limitations and suspicious behaviour

- **[medium] _task_digest hashes EVERY regular file under tasks/<id>/ with no exclusion list: __pycache__, *.pyc, .DS_Store, editor droppings, and any file an integrity/versioning tool adds to the task dir all change the digest. Empty dirs and file modes are not hashed. The framing (path NUL bytes NUL) has no length prefix.**  
  evidence: jobs.py:185-194 (rglob('*') + is_file); worker/grader copy the snapshot to temp dirs (pipeline.py:90, grader.py:393) so the runner itself does not normally write into tasks/, but nothing prevents stray files  
  integration relevance: HIGH: a merged integrity subsystem that adds/rewrites any file under tasks/<id>/ (lock files, hashes, version metadata, task.json edits or the 18 version bumps) will change digests: in-flight evaluations snapshotted before the merge become unresumable ('changed since evaluation creation') and cross-evaluation reuse from pre-merge sources fails with 'incompatible'.
- **[medium] Drift is only checked at three moments: creation (implicit), resume (all snapshot tasks), and immediately before each NON-completed trial in the worker. It is not re-checked at dispatch/claim, not held during a trial, and not checked for completed/reused trials at worker start. A mutation during act/grade is undetected for that trial; the test itself shows trial 0 completing after task.json was mutated mid-run.**  
  evidence: worker.py:270-306 (check inside loop only for pending trials); jobs.py:844; tests/test_a3_boundaries.py::test_restored_snapshot_resume_reopens_only_blocked_positions (mutates task.json inside agent.act; first trial still completed)  
  integration relevance: A concurrent integrity/versioning process touching task files while a trial runs would not be caught for that trial; the recorded snapshot digest may not describe the pack actually graded.
- **[low] Reuse is all-or-nothing and its predicate compares the source snapshot to a snapshot recomputed from CURRENT task files. It cannot reuse a subset, mix reuse with new execution, or reuse evidence whose task pack has since changed. The task list comparison is order-sensitive (same tasks in a different order = 'incompatible').**  
  evidence: jobs.py:323,338-344 (expected==requested), 250-255 (ordered list)  
  integration relevance: After a task version bump or task.json change, every pre-merge evaluation becomes non-reusable ('incompatible'), by design of digest equality.
- **[medium] Reuse does not cross-check the raw run against the source trial/snapshot: runs.task_version, runs.agent, runs.task_id/idx are never compared to the trial's task_version/model. The 'origin' is inferred solely from runs.job_id, and only requires the origin job to exist and be non-legacy (its status and its trial's evidence_state are not checked). Source job status is not checked either.**  
  evidence: jobs.py:357-375; trial_detail SELECTs r.task_version AS run_task_version but never compares it (jobs.py:604-627)  
  integration relevance: An integrity subsystem that rewrites runs.task_version or flags/invalidates runs will not be honored by reuse or trial_detail unless it also alters evaluation_trials/snapshots; test_evaluation_identity.py::test_exact_run_route... shows a mutated runs.task_version still serves 200 on the exact route.
- **[medium] Worker takes model, backend and generation parameters from params_json via _job_params_from_row, not from the immutable snapshot. That projector silently drops unknown keys and falls back to JobParams() defaults (model 'mock', mock backend) if validation fails; the worker does not compare params to snapshot or check agent.name against snapshot model.**  
  evidence: jobs.py:112-138; worker.py:236,315-317; snapshot only used for task list  
  integration relevance: If a merge adds/renames JobParams fields, or a row fails validation, params can silently degrade to mock defaults while the snapshot still claims another model. Only tampering or schema drift triggers it; no test covers it.
- **[low] Docstring/label mismatch on 'explicit resume': startup (and worker.serve) automatically requeue and re-dispatch any 'running' job whose owner lock is free, without any explicit resume call and without up-front snapshot validation (per-trial validation still runs).**  
  evidence: main.py:48-70; worker.py:480; jobs.py:749-833  
  integration relevance: Post-merge, interrupted evaluations will auto-restart on app start and will block trials on any digest change introduced by the merge.
- **[low] Events run_diff/run_graded/run_scored are committed BEFORE the evidence transaction. A crash or failure between them and save_run leaves events claiming a scored run with no raw row.**  
  evidence: worker.py:324-377  
  integration relevance: Event stream is a projection, not proof; consumers must use evaluation_trials (docstring in jobs.py:1-7 says so).
- **[low] Trial left in 'claimed' by a hard crash is only reset by reclaim_stale_running while the job is 'running'. If the job is already 'failed' with a claimed trial (e.g. _release_claim itself raised), resume_job resets only blocked/unverifiable trials; the claimed row is never re-claimable, so the worker skips it and the job fails again with 'no verifiable evidence'.**  
  evidence: worker.py:308-311,165-174; jobs.py:863-869 (only trial_state='blocked')  
  integration relevance: Rare; any new failure path that leaves 'claimed' rows in a terminal job is unrecoverable via resume.
- **[low] resume of a running-but-dead-owner job is refused until the lease is stale (>=300s / timeout+60), because resume_job calls reclaim without recover_unlocked. Startup/serve use recover_unlocked=True. Owner lock is tempdir-scoped (TMPDIR-dependent) and same-host only; processes with different TMPDIR or containers do not see each other's lock, so protection falls back to lease age, which is renewed only between trials.**  
  evidence: jobs.py:847-850,780,72-80; touch_owner only per trial (worker.py:273)  
  integration relevance: Multi-process/container deployments after a merge could double-run a long trial after lease expiry, but fencing (owner_token/claim_token) still stops the loser from publishing.
- **[info] UNVERIFIABLE semantics exist: trial_state='blocked' + evidence_state='unverifiable' (worker task-pack verification failure), reuse errors 'unverifiable/unknown' for missing artifacts/origin, and job-level failure text 'no verifiable evidence'. There is no distinct job status for it; the job is simply 'failed'. Blocking is per task_id: ALL non-completed positions of that task (including 'claimed') are blocked, not just one idx.**  
  evidence: jobs.py:549-556; worker.py:290-306,396-410; jobs.py:863-869  
  integration relevance: A merged subsystem defining its own 'unverifiable'/'invalid' evidence state must not collide with evidence_state='unverifiable' semantics, which are tied to resume unblocking.
- **[low] Task path is built as db.ROOT/'tasks'/task_id from user input without sanitisation. Traversal is blocked only indirectly because task.json 'id' must equal the requested task_id string. task_version is coerced with str() in task_snapshot but compared against the raw spec value in load_task (task.version), so a numeric JSON version would permanently mismatch and block trials.**  
  evidence: jobs.py:199-212; worker.py:133-138; runner/afa_runner/task.py:122-124  
  integration relevance: If a versioning subsystem changes task.json 'version' to a non-string, every snapshot-bound trial becomes unverifiable.
- **[info] Fresh evaluations use deterministic per-idx seeds (base_seed+idx) and reuse the same agent instance per task; 'fresh' means re-executed, not statistically independent. Duplicate (agent,task,idx) tuples in raw runs are accepted by design; the legacy tuple route returns 409 ambiguous and aggregates pool raw rows.**  
  evidence: worker.py:313-317; routes_readonly.py:98-107; serialize.py:308-311  
  integration relevance: Any integrity logic keyed on (model,task,idx) will see multiple rows per key after ATLAS; must key on runs.id / evaluation_trials.
- **[info] job_runs and runs.job_id disagree by design for reused evidence (job_runs links the reuse job to the source's runs; runs.job_id stays the origin). link_run only sets runs.job_id when NULL.**  
  evidence: jobs.py:432-436,1019-1028  
  integration relevance: Consumers deriving 'runs belonging to evaluation X' via job_runs vs runs.job_id get different answers for REUSED trials.
- **[low] create_job reads (source snapshot, source rows, raw evidence) before its first write; under Python's default sqlite3 isolation those reads are outside the write transaction, so the source could change between verification and insert (only theoretically: source rows are never deleted/rewritten by ATLAS code).**  
  evidence: jobs.py:316-377 (SELECTs precede INSERT at :377)  
  integration relevance: An integrity subsystem that invalidates/deletes runs concurrently could race with reuse creation.

### Integration assumptions

- Task packs live at <db.ROOT>/tasks/<task_id>/ and must contain task.json with matching string-ish 'id' and a 'version'; jobs.py uses db.ROOT and worker.py uses its own TASKS_DIR (both ROOT/tasks). The tasks/manifest.json is NOT consulted for snapshots; a task dir not listed in the manifest still runs, and manifest lacks versions (only task.json version is used).
- afa.load_task additionally requires snapshot/ (snapshot_dir), domains in task.json; digest covers the whole dir, so grading/, reference/ and snapshot/ are all part of task identity.
- task_version semantics = task.json 'version' string; it is compared exactly and stored in three places (snapshot_json, evaluation_trials.task_version, runs.task_version via record.task_version). A version bump (ORACLE) without a matching evaluation is expected to invalidate resume and reuse of pre-existing evaluations.
- The task directory must be byte-stable between snapshot and use; no build artifacts, caches or generated files may be written into tasks/<id>/ or digests will drift.
- evaluation_jobs/evaluation_trials/job_events/job_runs/app_settings are owned by afa_api/db._APP_SCHEMA and validated by exact required-column lists and unconditional unique keys; a merge that alters these tables (columns or PKs) causes migrate() to raise RuntimeError and every control route to return 503 (fail closed, no drop).
- runs table shape (columns incl. job_id) is owned by runner store SQLITE_SCHEMA; ATLAS depends on save_run(commit=False, job_id=...) and on the caller (worker) holding the single connection so raw insert and trial completion share a transaction. save_run must be given the same connection (worker checks store._conn is conn).
- Legacy rows (evaluation_jobs.mode='legacy', runs.job_id NULL, committed evidence DB) are never resumable, retryable or reusable and cannot serve as reuse origin.
- Foreign keys are enforced per connection (PRAGMA foreign_keys=ON); evaluation_trials.run_id must reference an existing runs.id.
- One process-local assumption: same-host flock under tempfile.gettempdir() is the liveness signal; lease age is only a diagnostic fallback.
- Snapshot identity for reuse is computed from CURRENT files at reuse-create time, so any subsystem that changes task content/version without re-snapshotting silently makes all older evaluations non-reusable/non-resumable.

### Open questions

- Whether any part of the runner/grader writes into tasks/<id>/ (e.g. pytest cache, __pycache__ during reference validation via validate_reference in pipeline.py) in non-default flows; I saw copytree-based workspaces and PYTHONDONTWRITEBYTECODE in sandbox.py:60 and no stray files in the frozen tree, but did not run anything.
- How evaluation_report.py and the aggregate projection (store_load/leaderboard) treat duplicate raw (agent,task,idx) rows and REUSED trials; out of scope here, only partially inspected (report tests at tests/test_evaluation_reports.py, canary at tests/test_phase0_acceptance_canary.py).
- Behavior of Path.rglob with symlinked task subdirectories under Python 3.13 in _task_digest; no symlinks exist in tasks/ today (find -type l returned none), so untested.
- Whether ORACLE's post-merge startup path (migrations, reports/app.sqlite seeding via ensure_working_db) would replay task-version changes into already-snapshotted evaluations; not determinable from ATLAS alone.
- No empirical probe was run (copy-tree probes not needed for the questions asked); all claims are from code reading plus test inspection, not execution.

---

## Task-version handling across ATLAS (1e1a788): storage, aggregation guard, projections, reuse, evidence vocabulary

**Storage.** Version is a plain TEXT copy taken at run time. `runs.task_version TEXT NOT NULL` (runner/afa_runner/store.py:53) is written by `save_run` from `record.task_version` (store.py:172-201). That value comes from `Task.version` = `task.json["version"]` (task.py:124, pipeline.py:154). `run_scores` has no version column, only `formula_version` (store.py:72). `evaluation_trials.task_version` and `task_digest` are also NOT NULL (db.py:136-153), copied from the evaluation snapshot. The snapshot is built by `jobs.task_snapshot()` (jobs.py:197-217), which reads `tasks/<id>/task.json` strictly and hashes the whole task directory (jobs.py:185-194). `db/schema.sql` (Postgres `task_versions`) is unused design.

**Two different sources of "current version".** Write path: strict `task.json` (jobs.py:197-217). Read path: `_current_task_version` (examples/report_combined.py:48-57) uses a manifest `"version"` key if present (no manifest item has one), else `<dir>/task.json`, and silently falls back to "1.0.0" if the file or key is missing.

**The only mixed-version guard** is `load_stores` (afa_api/store_load.py:135-178). It collects versions per (agent, task_id) cell and raises `ValueError("refusing to pool multiple task versions: ...")`.
- It is per cell. Different agents at different versions of the same task are pooled silently.
- `open_projection` maps the error to `ProjectionUnavailable` (projection.py:51-54), and `_project` returns HTTP 503 `{"error": <text>}` (routes_readonly.py:34-42).
- One mixed cell anywhere makes overview, leaderboard, domains, cell, run, meta and export return 503 (probe G1-G8); healthz returns 200 "degraded" (routes_readonly.py:55-61); `POST /reports/regenerate` returns 409.
- Not affected: `/runs/{id}`, `/jobs/*`, and `/jobs/{id}/report.json`.

**No staleness detection.** Nothing marks evidence as stale when the DB version differs from disk. Current and evaluated versions are exposed side by side (serialize.py:197-198, 391-394; TaskDetail.tsx:53-56, 96-97), but with no flag. Two small hints exist: the HTML report subtitle "Strengthened task versions awaiting reevaluation" (report_combined.py:177-196) and a tooltip badge (report_html.py:207-214), both on the report path only. CellPage.tsx:43 headlines "task version <current_version>" even when the cell's rows are older; the real versions are shown separately at CellPage.tsx:70-72.

**Evaluation-side drift checks** compare the snapshot with disk (version and digest), never the DB with disk. They are `validate_snapshot_tasks` (jobs.py:220-236) on resume, `_load_snapshot_task` (worker.py:129-142) before each trial, and `mark_trial_unverifiable` (jobs.py:539-558).

**Reuse** (jobs.py:317-375):
- The source must be an evaluation, not a legacy one, with a stored snapshot.
- `_snapshot_identity` equality covers model, backend, generation, the tasks list (task_id, task_version, task_digest, and list order) and repeats.
- Every source trial must be completed, carry evidence_state fresh or reused, and its trial version and digest must equal its own snapshot.
- Each source run must have `runs.job_id` non-NULL, a patch, at least one test result, and a non-legacy origin evaluation.
- `runs.task_version` is never compared with the trial or snapshot version. Test tests/test_a3_boundaries.py:951 mutates it to 'unrelated-version' and only checks that `/runs/{id}` still serves the row.
- Pre-ATLAS runs have `job_id` NULL and belong to no evaluation, so they can never be sourced. The historical DB has 0 `evaluation_jobs`, 0 `job_runs` and 0 runs with `job_id`. They appear only in the aggregates, labelled "captured" (serialize.py:184-188), with no legacy label.

**Vocabulary.**
- trial_state: pending, claimed, completed, blocked.
- evidence_state: missing, fresh, reused, unverifiable.
- comparability (jobs.py:659-666): "comparable" if fresh and patch and tests present; "provisional" if reused; omitted otherwise.
- kernel `provisional` = n_valid < 5, applied to cells and leaderboard entries (aggregate.py:25,162; ranking.py:18,65).
- domain `displayable` = at least 5 tasks and at least 25 runs (domains.py:17-18).
- There is no "official" state and no minimum-repeat gate on comparability.
- Nothing hides observed results: provisional entries are returned, and the UI ignores `displayable` (types.ts:97 is its only reference).
- Comparability is not tied to version currency.

**Probe (copy of tree, task.json bumped, mock backend).** Results are listed in the guarantee entries. Observed: 200s everywhere before any new run, 503 once a mixed cell exists, reuse 409 and resume 409 after a further bump. The frozen tree and `reports/runs.sqlite` were untouched (git status clean, sha matches).

**Prediction for the merged system, task X on disk 1.0.2, rows 1.0.1.**
- (a) Global leaderboard returns 200, pools the old rows unchanged, no flag.
- (b) Cell, model and task pages return 200 showing current 1.0.2 with evaluated ['1.0.1'].
- (c) A new evaluation snapshots 1.0.2 with a new digest. If the model already has (M, X) rows at 1.0.1, every projection returns 503 as soon as the first run persists.
- (d) The evaluation report shows only its own trials, at 1.0.2, "comparable".
- (e) Reuse from an old-version evaluation returns 409 "reuse source snapshot is incompatible"; reuse from legacy runs or a legacy or nonexistent evaluation returns 409 "unavailable or legacy".

### Guarantees (claim / evidence / proven-by / confidence)

- **Version is stored as TEXT NOT NULL in runs.task_version and evaluation_trials.task_version (plus task_digest). It is copied at save time from the loaded Task's task.json version. run_scores has no version column.**  
  evidence: runner/afa_runner/store.py:53,172-201; runner/afa_runner/pipeline.py:154; runner/afa_runner/task.py:124; afa_api/db.py:136-153; afa_api/worker.py:360-376  
  proven by: tests/test_phase0_acceptance_canary.py (asserts run task_version equals report snapshot version); runner/tests/test_store.py (round-trip of task_version)  
  confidence: `verified`
- **A single (agent, task) cell containing more than one task_version makes load_stores raise ValueError('refusing to pool multiple task versions: agent/task: v1,v2'). The API returns 503 with that exact text on overview, leaderboard, domains, cell, run, meta and export. healthz returns 200 with status 'degraded'. POST /reports/regenerate returns 409. Only /runs/{id}, /jobs/* and evaluation report endpoints keep working.**  
  evidence: afa_api/store_load.py:135-178; afa_api/projection.py:51-58; afa_api/routes_readonly.py:34-42,45-61; afa_api/routes_jobs.py:389-401,453-454  
  proven by: tests/test_api_readonly.py::test_mixed_version_refusal_surfaces_as_503 (injects one 2.0.0 row into a copied DB, checks the 503 text and each read route except /export and /overview-adjacent extras); runner/tests/test_report_combined.py::test_combined_report_refuses_to_pool_multiple_task_versions. My probe reproduced it on frozen code (G1-G9).  
  confidence: `verified`
- **The guard is per (agent, task) cell only. Cross-agent version differences for the same task are silently pooled: the task-scoped leaderboard and the global leaderboard rank agents at different versions side by side, with no warning.**  
  evidence: afa_api/store_load.py:153-155,168-172; runner/afa_runner/report.py:47-65  
  proven by: none (probe B3/B4: agent 'mock' at 1.0.2 ranked next to five agents at 1.0.1 on sanitize-filename, HTTP 200)  
  confidence: `verified`
- **No code compares DB task_version to the current on-disk task version to mark evidence stale. The API exposes current_version and evaluated_versions/task_versions side by side and nothing else. The only 'stale' hints are the report_combined HTML subtitle and a report_html tooltip, and only on the standalone report path when no mixed cell exists.**  
  evidence: afa_api/serialize.py:197-198,391-394; examples/report_combined.py:177-196; runner/afa_runner/report_html.py:207-214; web/src/pages/TaskDetail.tsx:53-56,96-97; web/src/pages/CellPage.tsx:43,70-72  
  proven by: runner/tests/test_report_combined.py (subtitle text 'frozen to the stored task versions'); tests/test_api_readonly.py::test_meta_shape (only asserts evaluated_versions contains 1.0.0). Probe: cell for disk 1.0.2 vs rows 1.0.1 returned 200 with current_version '1.0.2', task_versions ['1.0.1'], state 'captured'.  
  confidence: `verified`
- **Evaluation creation snapshots version and a sha256 digest of the entire task dir, read strictly from tasks/<id>/task.json. Resume and per-trial execution refuse if either has drifted since creation (409 on resume; trial marked blocked/unverifiable in the worker).**  
  evidence: afa_api/jobs.py:185-236,304-311; afa_api/worker.py:129-142,297-306; afa_api/jobs.py:539-558,836-873  
  proven by: tests/test_a2_boundaries.py and tests/test_a3_boundaries.py (drift/resume tests, not individually re-read). Probe D2: resume after version bump returned 409 'changed since evaluation creation; refusing snapshot drift'.  
  confidence: `verified`
- **Reuse compatibility is snapshot-identity equality, covering model, backend, generation, the tasks list (task_id, task_version, task_digest, order-sensitive) and repeats. In addition each source trial's own version and digest must match the source snapshot and the source raw run must have job_id, patch and test rows. runs.task_version itself is NOT compared.**  
  evidence: afa_api/jobs.py:288-295,317-375  
  proven by: tests/test_a3_boundaries.py::test_reuse_rejects_each_incompatible_snapshot_identity_atomically (parametrized over model, backend, generation, task_version, task_digest, mutating the stored snapshot); ::test_exact_native_runs_keep_distinct_patch_and_test_content mutates runs.task_version but only checks /runs/{id}. Probe D1: reuse from a 1.0.2 evaluation after bumping to 1.0.3 returned 409 'reuse source snapshot is incompatible'.  
  confidence: `verified`
- **Pre-ATLAS (legacy) runs can never be reuse sources. A source must be a non-legacy evaluation with a snapshot, and its raw runs must have non-NULL job_id whose origin evaluation is non-legacy. Historical runs.sqlite has 0 evaluation_jobs and 0 runs with job_id. Legacy runs appear only in aggregates as plain 'captured' with no legacy label.**  
  evidence: afa_api/jobs.py:321-322,365-375; afa_api/db.py:417-435 (mode DEFAULT 'legacy'); afa_api/serialize.py:184-188; sqlite counts on a copy of reports/runs.sqlite  
  proven by: tests/test_a3_boundaries.py::test_reuse_rejection_covers_incompatible_task_identity_and_unverifiable_evidence. Probe F1: nonexistent/legacy source returned 409 'reuse source evaluation is unavailable or legacy'.  
  confidence: `verified`
- **Evidence vocabulary: trial_state (pending, claimed, completed, blocked), evidence_state (missing, fresh, reused, unverifiable), trial comparability ('comparable' for fresh with patch and tests; 'provisional' for reused; omitted if artifacts are incomplete), and kernel provisional (n_valid < 5). There is no 'official' state and no minimum-repeat threshold on comparability. Comparability ignores whether the version is current.**  
  evidence: afa_api/db.py:136-153; afa_api/jobs.py:600-667; kernel/afa_kernel/aggregate.py:25,162; kernel/afa_kernel/ranking.py:18,65; grep for 'official' finds nothing  
  proven by: tests/test_a3_boundaries.py::test_trial_detail_does_not_claim_complete_or_comparable_without_test_artifacts; probe B5/E1/G11 (fresh gives 'comparable', reused gives 'provisional', including after the on-disk version moved on)  
  confidence: `verified`
- **No threshold hides observed results. Leaderboard entries with n < 5 are returned as provisional (unranked). Cell aggregates carry provisional=true and are still shown. Domain scores are returned with displayable=false (needs at least 5 tasks and 25 runs) and the web UI never reads that flag.**  
  evidence: kernel/afa_kernel/ranking.py:65-113; afa_api/serialize.py:67,78,95,205-209; kernel/afa_kernel/domains.py:17-18,47; grep of web/src for displayable (types.ts:97 only)  
  proven by: none directly; probe B3 shows the 'mock' entry n=2 provisional=True still listed  
  confidence: `verified`
- **Evaluation reports are strictly evaluation-scoped. They report each trial's snapshot version and digest and never consult runs.task_version, DB aggregates, or the current on-disk version. A report stays 'comparable' with its original version after the on-disk version changes.**  
  evidence: afa_api/evaluation_report.py:242-262,289-305; afa_api/jobs.py:604-667  
  proven by: tests/test_evaluation_reports.py, tests/test_phase0_acceptance_canary.py (evaluation-scoped identity, not staleness). Probe D3: after bumping 1.0.2 to 1.0.3 the report still says 1.0.2 comparable with empty limitations.  
  confidence: `verified`
- **Reuse creates no new raw runs. The reusing evaluation's trials point to the source run_id with evidence_state 'reused' and the current snapshot version, which equals the source version by identity. Aggregates are therefore unaffected by reuse.**  
  evidence: afa_api/jobs.py:395-436; afa_api/worker.py:270-289  
  proven by: tests/test_a3_boundaries.py (asserts runs count unchanged after reuse). Probe E1 confirmed reused_runs=2, trials 'reused'/'provisional'.  
  confidence: `verified`

### Schema / state facts

- runs(id, task_id, task_version TEXT NOT NULL, agent, idx, status, transcript_hash, duration_ms, created_at, job_id): no UNIQUE constraint on (agent, task_id, idx) or on version (store.py:50-62).
- run_scores(run_id, ..., formula_version DEFAULT 'v0.1'): the only 'version' in run_scores is the formula version (store.py:64-74).
- evaluation_trials PK (evaluation_id, task_id, idx); columns task_version, task_digest, trial_state, evidence_state, run_id, source_evaluation_id, source_run_id, origin_evaluation_id (db.py:136-153).
- evaluation_jobs.mode is one of fresh, reuse or legacy. The migration adds it with DEFAULT 'legacy', so pre-ATLAS jobs are legacy. snapshot_json holds {model, backend, generation, tasks[{task_id, task_version, task_digest}], repeats} (jobs.py:245-272; db.py:417-427).
- Task digest = sha256 over sorted relative paths plus bytes of every file under tasks/<id>/, including task.json itself. Any version bump therefore changes the digest (jobs.py:185-194).
- Historical reports/runs.sqlite: 720 runs, 24 tasks, 6 agents, 5 runs per cell. Versions: 1.0.0 x120, 1.0.1 x510, 1.0.2 x90. It matches the on-disk task.json versions of the frozen ATLAS tree. It has 0 evaluation_jobs, 0 job_runs, 0 runs with job_id, and its evaluation_jobs table has no 'mode' column until migrate() runs.
- The default working DB is reports/app.sqlite, seeded by SQLite backup from reports/runs.sqlite only if absent (db.py:33-34,198-247). The evidence DB is refused as a writable target (db.py:65-73).
- API routes: GET /api/v1/{overview,leaderboard,domains/{agent},cell/{agent}/{task},run/{agent}/{task}/{idx},meta,healthz,export}, /runs/{id}, /jobs/{id}/{trials,results,report.json,report.md}, POST /jobs, /jobs/{id}/{resume,retry,cancel}, POST /reports/regenerate. Status codes: mixed-version read 503; create/reuse/resume state errors 409; regenerate mixed 409.
- Meta 'current_version' comes from manifest/dir task.json via _current_task_version; evaluated_versions = distinct runs.task_version per task_id across all agents (store_load.py:135,150-152,186-190).
- Synthetic oracle/noop baseline rows are stamped with the CURRENT version and exist only in the in-memory 'full' store, never in the DB (store_load.py:180-184). They are used only by build_run for synthetic agents.
- Frontend consuming versions: CellPage (header uses current_version, evidence strip uses task_versions), TaskDetail (current + evaluated), Tasks and AgentDetail (current_version column), RunPage (run.task_version). No stale/outdated UI element exists.

### Limitations and suspicious behaviour

- **[high] One mixed (agent, task) cell anywhere takes down ALL aggregate read endpoints (overview, leaderboard, domains, cell, run, meta, export) with 503, and also the report regenerate route. There is no per-cell or per-task degradation.**  
  evidence: store_load.py:168-178 raises before any store is returned. Probe G1-G9: all returned 503 after a fresh evaluation of an existing agent name (qwen3.5:9b) on a task whose version had changed.  
  integration relevance: After the merge, task X is at 1.0.2 while historical rows are at 1.0.1. Any new fresh evaluation whose model name matches an existing agent name (for example re-running qwen3.5:9b, or any model already in the copied DB) on a bumped task makes every dashboard route return 503 as soon as its first run is persisted, even mid-evaluation. New-model names (agents not in the DB) avoid it.
- **[high] The guard is per agent+task, not per task. Rows for the same task at different versions but different agents are pooled silently into task and global leaderboards, domain profiles and the meta 'evaluated_versions'. Nothing labels them non-comparable.**  
  evidence: store_load.py:153-155,168-172. Probe B3/B4: 'mock' at 1.0.2 sits in the same ranking as agents at 1.0.1.  
  integration relevance: After the merge, a new model evaluated on bumped tasks will be ranked against historical models at old versions, with no stale or non-comparable marking. Any Oracle-side comparability logic will not be reflected in ATLAS's pooling.
- **[medium] No stale/current comparison of DB version vs on-disk version in any decision path. CellPage's header shows current_version as 'task version' while the rows may be older; only the small evidence strip shows the real versions.**  
  evidence: web/src/pages/CellPage.tsx:43 versus 70-72; serialize.py:197-198  
  integration relevance: After the merge, cell pages for 1.0.2-bumped tasks will say 'task version 1.0.2' above 1.0.1 results, which is misleading. A merge that adds staleness marking has no existing hook to attach to except build_cell and build_meta.
- **[medium] Duplicate (agent, task, idx) rows are pooled without de-duplication. Two fresh evaluations of the same model and task at the same version double n in the cell aggregate, and the tuple-identity run route returns 409 ambiguous. Nothing prevents re-running.**  
  evidence: runs has no UNIQUE constraint (store.py:50-62); load_stores copies every row (store_load.py:149-157); build_run returns ambiguous (serialize.py:302-312). Probe C1: n_valid=4 with idx [0,0,1,1]; C2: 409 with candidate ids.  
  integration relevance: After the merge, a new evaluation of a task that already has historical rows for the same model (same idx 0..4) at the SAME version silently doubles the cell. The tests only assert n_valid >= 2 (tests/test_phase0_acceptance_canary.py:355-372).
- **[medium] Two divergent definitions of 'current version'. Reads use manifest (item['version'] if present) then <dir>/task.json, defaulting to '1.0.0' when the file or key is missing. Writes use strict tasks/<id>/task.json. If tasks/manifest.json ever gains a 'version' key, it overrides task.json on the read path only.**  
  evidence: examples/report_combined.py:48-57; store_load.py:83-85; jobs.py:197-217  
  integration relevance: If the merge adds version fields to the manifest, or moves or renames task dirs, meta.current_version can disagree with the evaluation snapshot version. A missing task.json silently reads as 1.0.0 on the read path.
- **[medium] runs.task_version is never cross-checked against evaluation_trials.task_version or the snapshot. Reuse, evaluation reports and comparability trust the trial row's version. The tests deliberately mutate runs.task_version to 'unrelated-version' and nothing detects it.**  
  evidence: jobs.py:357-364 (SELECT omits r.task_version); jobs.py:604 selects run_task_version but evaluation_report.py never exposes or checks it; tests/test_a3_boundaries.py:951; tests/test_evaluation_identity.py:359  
  integration relevance: After the merge, the two version sources for one evidence row can diverge silently. A version-bump tool that rewrites runs.task_version or trial rows independently would not be caught.
- **[medium] 'comparable' means only fresh evidence with complete artifacts. It ignores version currency, minimum repetitions and digest-vs-current. A trial stays 'comparable' forever even if the task later changes. 'provisional' means 'reused', unrelated to the kernel's n<5 'provisional' (two different meanings of the same word).**  
  evidence: jobs.py:659-666; kernel aggregate.py:162; probe D3  
  integration relevance: After the merge, the ATLAS 'comparable' label will not mean the same thing as any Oracle integrity or comparability verdict. There is no 'official' or 'unverifiable' evidence state for legacy historical rows; they surface as ordinary 'captured' with no label.
- **[low] Docstrings/prose slightly overstate. web Methodology says 'Every run retains a task version. The report path refuses to pool multiple versions inside a cell'. True, but the refusal is a single global 503, and the frozen-version notice claims 'Leaderboard values remain frozen to the stored task versions' only exist on the standalone HTML report, not the app.**  
  evidence: web/src/pages/Methodology.tsx:117-153; examples/report_combined.py:190-196  
  integration relevance: none beyond documentation drift
- **[medium] Tests hardcode fix-binary-search at 1.0.0 (run and meta assertions) against the seeded DB and on-disk task. Anchor assertions: current_version == '1.0.0', evaluated_versions contains '1.0.0', run task_version == '1.0.0'.**  
  evidence: tests/test_api_readonly.py:41,222,238,268-269; tests/test_phase0_live_projection.py:23,183  
  integration relevance: If the merged task pack bumps fix-binary-search (or the tasks the tests rely on) these ATLAS tests fail on assertion, not on real behaviour. Attribute such failures to the fixture, not the code.
- **[low] The guard reads only runs that join both run_scores and diffs. A runs row lacking either is invisible to the guard and to aggregates. The evaluation-side reuse check does require them.**  
  evidence: runner/afa_runner/store.py:282-291 (inner joins)  
  integration relevance: A version-bump migration that inserts partial rows would evade the guard.
- **[info] Evaluation-level guarantees hold only within ATLAS's own write path. The worker pins version and digest by re-reading disk before each trial; it does not verify that the task loaded by run_once is the same object the digest covered (a TOCTOU window between _load_snapshot_task and run_once is theoretically possible, but both read the same dir immediately).**  
  evidence: worker.py:129-142,298,324  
  integration relevance: none expected

### Integration assumptions

- tasks/<id>/task.json exists with 'id' matching the directory name and a string 'version'; snapshot creation raises JobStateError (409) otherwise (jobs.py:197-217). Tasks are located at db.ROOT/'tasks'/<task_id>, not through the manifest.
- tasks/manifest.json entries carry 'id' and 'dir'; the manifest has no 'version' key. If one appears it silently overrides task.json on the read path (report_combined.py:48-50).
- One version per task per agent per DB: any cell with two versions is treated as a fatal read error. A migration that leaves old-version rows alongside new-version rows for the same agent and task (an Oracle re-evaluation into the same working DB) will trip the guard.
- Task version strings are opaque and compared by exact string equality; no semantic version ordering exists, so nothing like 'latest' is ever selected.
- Task digest covers every file under the task dir including task.json, so any Oracle change to task files or version invalidates reuse and resume for older snapshots. A pure version-string bump with no other change still changes the digest.
- Working DB is a copy of reports/runs.sqlite: the app adds app tables and a nullable runs.job_id additively; existing runs rows are never rewritten, so old versions persist exactly as stored.
- Agent identity is the model name string (agent == params.model). Evaluating a model with an existing name merges into that agent's cells.
- Historical evidence rows never belong to an evaluation, so the reuse and comparability machinery can never touch them.

### Open questions

- How does the SPA render a 503 from /overview or /leaderboard (error banner, blank, retry loop)? I did not find any handler for 503 or 'degraded' in web/src beyond the type definition in types.ts; the exact UX is unverified.
- Does the ORACLE side expect a per-task or per-row 'not current / unverifiable' label from the API? ATLAS has no such field, so the merge will either need to add one or leave stale evidence invisible.
- After the merge, will re-evaluations of bumped tasks be run under new model names or the same names? Same names trigger the global-503 path and idx collisions; the merge plan should say.
- Are the ATLAS test-suite fixtures (fix-binary-search 1.0.0) among the 18 bumped tasks? Only the seeded DB and on-disk version determine whether the hardcoded-version assertions still pass.

---

## Run forensics, evaluation-scoped results, report.json/report.md, artifact/evidence/comparability states (ATLAS 1e1a788, standalone)

**Run identity.** `GET /api/v1/runs/{run_id}` (routes_readonly.py:109-119) reads one native `runs.id` via a read-only connection and does NOT go through `open_projection`, so it is unaffected by mixed-version refusal. It INNER JOINs `run_scores` and `diffs` (serialize.py:235-237): a run missing either row is reported as 404 found:false even though the raw row exists. The legacy tuple route `GET /run/{agent}/{task_id}/{idx}` (routes_readonly.py:98-106; serialize.py:292-313) returns 409 with `ambiguous:true, found:false, candidate_run_ids:[...]` when several rows match. It is wrapped in `_project`, so if the DB has any mixed-version (agent,task) cell, `load_stores` raises first and the answer is 503, not 409 (probe confirmed).

**Results.** `/jobs/{id}/results` is an alias of `/trials` (routes_jobs.py:178-193). It calls `evaluation_results` (jobs.py:670-689): a Job projection plus `trial_detail` per `evaluation_trials` row for that evaluation_id. Every join is keyed on that row's `run_id` (jobs.py:602-612). A reused trial's `run_id` is the SOURCE evaluation's native run id (a shared row, not a copy: create_job jobs.py:406-431), with `evidence_state='reused'` and `source_evaluation_id`, `source_run_id` and `origin_evaluation_id` (from `runs.job_id`). Evaluation A can only include B's evidence if A's trial rows point at B's run ids, which only reuse mode does, explicitly labelled. Fresh runs are written with `job_id` and the trial link in one transaction (worker.py:355-378). The result and report queries never filter on `runs.job_id` or on model, task and idx.

**report.json** is not persisted. It is rebuilt per request from SQLite by `build_evaluation_report` (evaluation_report.py:202-359) inside one explicit read transaction. Nothing uses a clock or randomness; trials are ordered by (task_id, idx), and limitations are `sorted(set())`. Top-level keys: schema_version(=1), evaluation_id, status, mode, created_at, started_at, finished_at, model, backend, provider, evaluation_parameters, generation, task_snapshots, counters, counter_semantics, trials, limitations. Per-trial keys: task_id, idx, task_version, task_digest, run_id, trial_state, evidence_state, source_evaluation_id, source_run_id, origin_evaluation_id, outcome, artifact_state, comparability, error_message. Backend, generation, model and task_snapshots come from `snapshot_json` first, then from an independently parsed `params_json`, else null plus a limitation. Nothing is defaulted, and non-finite numbers and credential-bearing backends are dropped. `render_markdown` is a pure function of the report dict (:386-450), so md and json share one builder. The two routes are separate requests with no shared version or hash. A restart test proves byte equality.

**States.** artifact_state (`trial_detail`, jobs.py:632-660): `absent` (no run_id); `unavailable` (raw or score row missing); `partial` (score exists but patch_text is NULL or there are zero test_results); `complete`. Comparability is set only when artifacts are complete: `comparable` if evidence_state=='fresh', `provisional` if 'reused'. Otherwise the key is absent and the report emits null. Nothing ties "comparable" to a reference (task_version, other evaluation, model). Evidence states written by code: missing, fresh, reused, unverifiable. Counters: passed/failed/voided count only fresh completed trials with an outcome; reused are counted only in `reused`.

**Task snapshots.** `task_snapshots` come from `snapshot_json`. Per-trial task_version and task_digest come from `evaluation_trials`, copied at creation. No code cross-checks snapshot against trial rows, and `run_task_version` is selected (jobs.py:604) but never used.

**Version handling.** Only the aggregate path pools or refuses on task_version: store_load.py:168-178 and report_combined.py:159-169 refuse the whole DB if any (agent,task) cell holds more than one version. This yields 503 on overview, leaderboard, cell, domains, meta, export, the legacy run route and degraded healthz, and 409 on /reports/regenerate. Job creation, resume and reuse fail closed on snapshot drift or identity mismatch. Scores are computed only in the kernel via afa.leaderboard, task_aggregate, domain_profile and render_report. The report code only counts persisted booleans.

**Tests.** test_evaluation_reports.py runs the real pipeline with the mock agent on a copy of the evidence DB (`shutil.copy(db.DB_PATH)`). Corruption cases are injected by direct SQL. test_report_combined.py uses tiny synthetic DBs and monkeypatched failures.

### Guarantees (claim / evidence / proven-by / confidence)

- **GET /api/v1/runs/{run_id} is an exact native-id lookup that is independent of aggregate projection, so it still returns 200 when the DB has mixed task versions.**  
  evidence: routes_readonly.py:109-119 (uses db.connect_readonly directly, not open_projection); serialize.py:370-378  
  proven by: tests/test_evaluation_identity.py::test_exact_run_route_and_ambiguous_tuple_route (exact 200 after mixed version, overview 503); tests/test_a3_boundaries.py lines ~940-975; probe 'BYID mixed 200'  
  confidence: `verified`
- **Legacy (agent,task,idx) lookup with multiple matching raw rows returns HTTP 409 with body {agent,task_id,idx,found:false,ambiguous:true,synthetic:false,known_task,candidate_run_ids:[ids ordered by r.id]}. It never picks a row for a non-synthetic agent when >1 rows exist.**  
  evidence: serialize.py:292-312; routes_readonly.py:104-105  
  proven by: test_evaluation_identity.py::test_exact_run_route_and_ambiguous_tuple_route (asserts 409 and set of candidate ids); probe confirmed body  
  confidence: `verified`
- **Tuple route on a DB with any mixed-version (agent,task) cell returns 503 {'error':'refusing to pool multiple task versions: ...'} and never reaches the ambiguity check.**  
  evidence: routes_readonly.py:34-42,98-103; projection.py open_projection; store_load.py:168-178  
  proven by: none directly (identity test asserts /overview 503 only); probe 'LEGACY mixed 503'  
  confidence: `verified`
- **/jobs/{id}/results returns only trial rows belonging to that evaluation_id, each joined to the raw run by the trial's own run_id. Reused trials are marked evidence_state='reused' with source_evaluation_id/source_run_id/origin_evaluation_id and share the source's native run row (no new raw rows).**  
  evidence: jobs.py:464-470,600-667,670-689; create_job jobs.py:406-431; routes_jobs.py:190-193  
  proven by: test_evaluation_reports.py::test_reuse_report_marks_source_without_new_raw_runs (runs table id list unchanged after reuse); ::test_reports_are_scoped_deterministic_and_survive_app_reopen (two evaluations of same model have disjoint run_ids and disjoint markdown)  
  confidence: `verified`
- **report.json and report.md are pure functions of persisted SQLite state and are regenerable after restart. Nothing is stored, no clock or randomness is used, and output is deterministic (sorted trials and limitations, sort_keys JSON in md).**  
  evidence: evaluation_report.py:202-359, 362-450; routes_jobs.py:196-217  
  proven by: test_evaluation_reports.py::test_reports_are_scoped_deterministic_and_survive_app_reopen (new create_app on same DB yields equal JSON and equal markdown)  
  confidence: `verified`
- **The report is built inside a single explicit read transaction (BEGIN on a mode=ro connection), so concurrent writers cannot tear it.**  
  evidence: evaluation_report.py:350-359; routes_jobs.py:196-217 use db.connect_readonly  
  proven by: test_report_uses_one_coherent_read_snapshot (interleaves a writer after trial_rows and asserts the stale-consistent view); test_report_routes_use_readonly_connections (only checks connect_readonly is called twice)  
  confidence: `verified`
- **Unknown, invalid or credential-bearing persisted provenance is reported as null plus a limitation. Report never substitutes schema defaults or 'mock'. Backend is exposed only if kind is in {mock,ollama,openai_compat} and Backend model validates.**  
  evidence: evaluation_report.py:18-95,127-156,183-199,265-287  
  proven by: test_report_does_not_invent_defaults_for_invalid_persisted_params (many raw-inserted malformed rows; secrets absent from JSON and md)  
  confidence: `verified`
- **Missing evidence is surfaced, not hidden: no run_id gives artifact_state 'absent'; missing raw or score row gives 'unavailable' with outcome null; missing patch or test_results gives 'partial' with comparability null. Each also yields a limitation string and counters.unavailable.**  
  evidence: jobs.py:632-660; evaluation_report.py:183-199,313  
  proven by: test_reports_show_partial_missing_and_unverifiable_artifacts; test_report_counts_incomplete_and_outcome_states (pending/blocked); probe 'REPORT A after diff del' shows partial  
  confidence: `verified`
- **Counters are counts over persisted per-trial outcomes: passed/failed/voided only from fresh completed trials with an outcome; reused trials are counted only in 'reused'. A voided trial is never counted as passed even if functional_pass=1. No score arithmetic is done in the report layer.**  
  evidence: evaluation_report.py:289-325  
  proven by: test_report_counts_incomplete_and_outcome_states (failed and voided cases); test_reuse_report_marks_source_without_new_raw_runs (passed==0, reused==2)  
  confidence: `verified`
- **Comparability semantics: 'comparable' iff evidence_state=='fresh' and artifacts complete; 'provisional' iff evidence_state=='reused' and artifacts complete; otherwise absent (null in report).**  
  evidence: jobs.py:659-666  
  proven by: test_evaluation_reports.py (comparable on fresh, provisional on reused, None on partial); tests/test_a3_boundaries.py::test_trial_detail_does_not_claim_complete_or_comparable_without_test_artifacts  
  confidence: `verified`
- **Mixed-task-version pooling is refused fail-closed on the aggregate paths (projection routes and report_combined.build_report) with an explicit error; never silently pooled. report.json and /runs/{id} do not participate.**  
  evidence: store_load.py:168-178; report_combined.py:159-169; projection.py; routes_jobs.py:395-401 (409)  
  proven by: runner/tests/test_report_combined.py::test_combined_report_refuses_to_pool_multiple_task_versions; test_evaluation_identity.py (overview 503)  
  confidence: `verified`
- **report_combined.build_report closes both the disk and in-memory aggregate stores on failure and reads only persisted rows (no hard-coded KNOWN_OLD), adding only the two labelled synthetic baselines.**  
  evidence: report_combined.py:103-215  
  proven by: test_report_combined.py::test_combined_report_closes_aggregate_on_synthetic_failure / _on_render_failure / ::test_combined_report_uses_db_rows_and_labels_only_synthetic_baselines  
  confidence: `verified`

### Schema / state facts

- Routes: GET /api/v1/runs/{run_id}; GET /api/v1/run/{agent}/{task_id}/{idx} (legacy, 409 on ambiguity); GET /api/v1/jobs/{id}/results (alias of /trials, results built by jobs.evaluation_results); GET /api/v1/jobs/{id}/report.json; GET /api/v1/jobs/{id}/report.md (text/markdown); GET /api/v1/jobs/{id}/trials/{task_id}/{idx}; POST /api/v1/reports/regenerate (409 on mixed-version ValueError, 503 on OSError/sqlite3.Error). Unknown evaluation returns 404 {error:'job not found'} on results and report routes.
- REPORT_SCHEMA_VERSION = 1 (evaluation_report.py:12); the snapshot_json schema_version is also 1 (jobs.py:255) but the report does not read or validate it.
- report.json top-level keys (exact, in order): schema_version, evaluation_id, status, mode, created_at, started_at, finished_at, model, backend, provider, evaluation_parameters, generation, task_snapshots, counters, counter_semantics, trials, limitations.
- evaluation_parameters keys: model, name, repeats, base_seed, temperature, request_timeout_s, backend, source_evaluation_id. generation keys: base_seed, temperature, request_timeout_s, seed_provenance, timeout_provenance. counters keys: total, completed, passed, failed, voided, reused, incomplete, unavailable (each with a counter_semantics string).
- Per-trial keys: task_id, idx, task_version, task_digest, run_id, trial_state, evidence_state, source_evaluation_id, source_run_id, origin_evaluation_id, outcome{status,functional_pass,voided,final_score}|null, artifact_state, comparability|null, error_message. Trial task_digest is not in trial_detail/results output, only in the report.
- evaluation_trials: PK (evaluation_id,task_id,idx); columns task_version, task_digest (NOT NULL), trial_state (default 'pending'), evidence_state (default 'missing'), run_id REFERENCES runs(id), source_evaluation_id, source_run_id, origin_evaluation_id, claim_token, claimed_at, completed_at, error_message. No CHECK constraints on trial_state or evidence_state (db.py:136-153).
- trial_state values written by code: pending, claimed, completed, blocked. evidence_state values written: missing, fresh, reused, unverifiable. evaluation_jobs.mode in {fresh,reuse,legacy}; status in {queued,running,succeeded,failed,canceled}.
- artifact_state values: absent | unavailable | partial | complete (report defaults to 'unavailable' if detail is missing). comparability values: comparable | provisional | null.
- runs table has no UNIQUE on (agent,task_id,idx); job_id is nullable (legacy rows NULL). run_scores PK is (run_id, formula_version) so multiple score rows per run are schema-legal. Only 'v0.1' is written by code.
- Fresh trials: runs row inserted with job_id=evaluation id, and evaluation_trials updated to completed with origin_evaluation_id=evaluation id, in one transaction (store.save_run commit=False + complete_trial, worker.py:355-378). Reuse trials: created already completed at create_job, run_id = source trial's run_id, origin = runs.job_id of that raw row; source must have runs.job_id NOT NULL and origin job mode != 'legacy'.
- Reuse requires _snapshot_identity equality of model, backend, generation, tasks (ids, versions, digests) and repeats between source and new snapshot (jobs.py:288-301, 316-321).
- Report/results/read routes open db.connect_readonly (mode=ro); connect_readonly raises if file absent (db.py:183-195).

### Limitations and suspicious behaviour

- **[medium] Latent arbitrary-row pick: the run_scores PK is (run_id, formula_version), but by-id lookup (fetchone), trial_detail (LEFT JOIN run_scores + fetchone) and the tuple route JOIN run_scores with no formula_version filter. If a run ever has two score rows, /runs/{id} and trial_detail silently return one of them, and tuple-route candidate_run_ids contains duplicate ids (probe: [1221,1221,1223]). refresh_counters would also double-count.**  
  evidence: serialize.py:221-239,372-378; jobs.py:602-612,561-575; runner store.py:64-73; probe: inserted formula_version='v9' row, then /runs/1221 returned 200 with the v0.1 score and candidate_run_ids repeated 1221  
  integration relevance: If the merged benchmark-integrity engine adds a second score formula or rescoring rows (new formula_version) for the same run, ATLAS forensic and report paths will silently pick one score with no error. No current ATLAS code writes a non-v0.1 row, so it is latent.
- **[high] Comparability never checks task_version/digest of the RUN row against the trial/snapshot. runs.task_version is selected as run_task_version but never used. A trial whose raw run has a different task_version still shows comparable/complete with trial.task_version from evaluation_trials.**  
  evidence: jobs.py:604 (unused alias), 659-666; probe: set runs.task_version='9.9.9' for a run in evaluation B; report.json still showed task_version 1.0.0, comparability 'comparable', limitations []  
  integration relevance: After merge, if oracle-side integrity bumps or rewrites runs.task_version (18 versions bumped) or reuse maps to old-version runs, ATLAS reports will present 'comparable' with no version-mismatch limitation. Any integrity check has to be added here.
- **[medium] Snapshot vs stored evidence disagreement is silent. task_snapshots (snapshot_json) and per-trial task_version/task_digest (evaluation_trials) are independent copies; the report never compares them or adds a limitation on disagreement.**  
  evidence: evaluation_report.py:215,246-250; probe: overwrote trial task_digest/task_version with 7.7.7/sha256:deadbeef; report showed trials 7.7.7 vs task_snapshots 1.0.0, no limitation  
  integration relevance: A version-bump that updates one location but not the other will produce internally inconsistent reports without warning.
- **[low] evidence_state and trial_state are unvalidated free text: an unknown evidence_state (probe: 'bogus') passes through verbatim, gets comparability null, and is excluded from passed/failed/voided/reused counts while still counted in completed. There is no limitation for the unknown value. The DB has no CHECK constraints.**  
  evidence: evaluation_report.py:289-315; db.py:142-143; probe 'BOGUS' output: counters completed=2 passed=0 failed=0 reused=0 unavailable=0  
  integration relevance: Any new evidence state introduced by the merge (e.g. a 'quarantined' or 'stale' state) would be silently counted as completed but not classified.
- **[low] /runs/{id} returns 404 found:false (not 'partial') when the run exists but lacks a run_scores or diffs row, because of INNER JOINs. It is indistinguishable from a nonexistent id, and it always hard-codes known_task=True.**  
  evidence: serialize.py:235-237,370-378; probe: deleting diffs row gave 404 {'run_id':1221,'found':false,'synthetic':false} while report.json showed artifact_state 'partial' and outcome available for the same run  
  integration relevance: Forensics and report disagree on partially written runs; an integrity subsystem that voids or strips diffs would make runs unreachable by id.
- **[medium] Legacy tuple route ordering: mixed-version refusal (503) pre-empts the 409 ambiguity response, and any mixed cell anywhere in the DB blocks tuple lookups for all agents/tasks. Documentation says 'Run identity is (agent, task_id, idx) — never runs.id' (routes_readonly.py:13-14, serialize.py:414) but /runs/{id} now exists (stale docstring/meta note).**  
  evidence: routes_readonly.py:34-42,98-106; serialize.py:414; probe 'LEGACY mixed 503'  
  integration relevance: After the merge, legacy history at old versions plus fresh evaluations at bumped versions of the same (agent,task) would make ALL aggregate routes 503 and POST /reports/regenerate 409. Forensics by id, jobs, results and report.json would keep working.
- **[medium] Same-version duplicate runs (same agent,task,idx from different evaluations) are not refused by aggregate pooling: load_stores copies every row into the in-memory store with no uniqueness check, so aggregates count both. Only the tuple route detects ambiguity; leaderboard/overview do not.**  
  evidence: store_load.py:143-157,168-178 (refusal keyed only on version-set size); runs has no UNIQUE(agent,task_id,idx); probe: two evaluations of model 'probe-m' gave a 409 tuple lookup while /leaderboard stayed 200 until versions diverged  
  integration relevance: Evaluation-scoped identity fixes forensics but not aggregate pooling. Merged version-aware pooling should decide whether repeated fresh evaluations at the same version double-count.
- **[low] Results route (/results, /trials) is not tolerant of malformed job rows the way report.json is: it goes through get_job -> Job validation, so a status or mode outside the Literals, or non-dict snapshot_json, would raise (500). Report reads the row directly to avoid this. Also, results embed the raw snapshot, unlike the report's sanitised backend.**  
  evidence: jobs.py:141-171,452-457,670-689; schemas.py:21,27,109-123; evaluation_report.py:205-209  
  integration relevance: None directly; inferred from code (not probed) that a row with unexpected status or mode makes /results 500 while report.json succeeds.
- **[low] Report JSON/MD reflect live evidence, but Job counters (evaluation_jobs.*_runs) are persisted at run time, so post-hoc edits to run_scores leave job counters stale and the report is the source of truth. report.json and report.md come from separate requests with no shared version hash, so a change between the two requests can make them disagree.**  
  evidence: jobs.py:561-588; routes_jobs.py:196-217; test_report_counts_incomplete_and_outcome_states mutates run_scores and only checks the report  
  integration relevance: Integrity actions that alter scores after the fact will change report counters but not job counters.
- **[low] Markdown is not escaped: error_message and limitation text (which can contain DB-supplied error strings, backticks or newlines) are interpolated raw, so structure can be broken. The md also omits the per-trial task_digest that the JSON carries.**  
  evidence: evaluation_report.py:442-448,183-189  
  integration relevance: none
- **[info] Report routes have no error handling for a missing DB file or an un-migrated DB (no evaluation_jobs table): sqlite3.OperationalError from connect_readonly or the query is unhandled and surfaces as a 500. Startup migration normally prevents this.**  
  evidence: routes_jobs.py:196-217; db.py:183-195  
  integration relevance: none unless the merge changes DB bootstrap.
- **[info] Coherent-snapshot test asserts read-transaction isolation only via monkeypatched trial_rows and a writer on a second connection; test_report_routes_use_readonly_connections only counts connect_readonly calls (2), it does not prove the connections are actually mode=ro against writes.**  
  evidence: tests/test_evaluation_reports.py:680-733  
  integration relevance: none

### Integration assumptions

- Every task the evaluation covers exists at tasks/<task_id>/task.json with fields 'id' (must equal directory name) and 'version' (stringified); the digest is sha256 over ALL files under the task dir (sorted relative paths + bytes). Any merge that adds files to the task dirs (e.g. version bump artifacts) changes task_digest and blocks resume and reuse (jobs.py:185-236).
- task_version semantics: a string copied from task.json at evaluation creation into snapshot_json and evaluation_trials; the raw runs.task_version is written from the loaded Task (record.task_version). ATLAS assumes these agree but never verifies it in reports; worker verifies only version+digest against the snapshot at execution time (worker.py:129-142).
- runs.job_id (nullable) is the origin evaluation id; legacy rows have NULL and are unreusable ('unknown or unverifiable origin'). Reuse requires the source to have complete patch and test_results.
- One (agent = model string) per evaluation: 'runs.agent' is the model name; aggregate pooling and the tuple route key on (agent,task_id,idx) with no backend or evaluation dimension.
- Each run has exactly one run_scores row (formula_version 'v0.1'); reports and trial_detail use LEFT JOIN + fetchone without a formula_version filter.
- evaluation_trials rows are created only by create_job (all rows up front); the report treats total = number of trial rows, not params.repeats*tasks.
- The only mixed-version guard is load_stores/build_report keyed per (agent, task). A merge that legitimately stores multiple task versions per cell (e.g. old evidence plus post-bump reruns) will trigger 503/409 refusals on all aggregate endpoints.
- reports/runs.sqlite is immutable evidence; writable working copy is reports/app.sqlite (or AFA_DB_PATH). app.state.db_path selects the DB for every route, including report routes.
- Scoring math lives entirely in afa_kernel/afa_runner (leaderboard, task_aggregate, domain_profile, render_report, RunScore from run_once). The ATLAS report and projection code only reads persisted score columns and counts them; the report route calls none of the scoring functions.

### Open questions

- Should a run row whose runs.task_version disagrees with the trial's task_version or the snapshot be reported as non-comparable or with a limitation? ATLAS currently does not, and this is the natural attachment point for any version-integrity check.
- What is the intended handling of multiple run_scores rows (formula_version) per run? By-id, trial_detail and refresh_counters all assume one.
- Is same-version, same-(agent,task,idx) duplication across evaluations meant to be pooled by aggregate views, given that only the tuple route treats it as ambiguity?
- Are 'comparable'/'provisional' meant to be asserted relative to any reference set? The code defines them purely by evidence_state plus artifact completeness, and the 'to what' is undefined.
- Probe used a temp copy at scratchpad/probe-forensics with mock backend only. Real ollama/openai_compat evaluations (seed_provenance='requested' on non-mock) were not exercised; report handling of those relies on code reading only.

---

## ATLAS canonical runtime DB, evidence immutability, migrations, dynamic target discovery, live projections

**Selection.** The writable runtime DB is resolved by `resolve_db_path` (afa_api/db.py:39-50): explicit arg (`app.state.db_path` or worker arg), then `AFA_DB_PATH`, then `reports/app.sqlite`. An empty string falls through to the next level. `reports/runs.sqlite` (`EVIDENCE_DB_PATH`, db.py:33) is never a default. `assert_writable_runtime_path` (db.py:65-73) rejects it by path or `samefile` (so symlinks/hardlinks are caught). It runs in `connect`, `ensure_working_db` and `migrate` (via `_guard_migration_target`, db.py:379-388). The API binds through `app.state.db_path`; the worker subprocess binds through env. Only afa_app.py:74,116,127 keeps the two in agreement.

**Protection and seeding.** The evidence file is opened only through a `mode=ro` URI (`connect_readonly`, db.py:183-195). `ensure_working_db` (db.py:198-247) runs the SQLite backup API from that read-only handle into a `mkstemp` file in the target directory, then `os.link(tmp, target)` publishes it without clobbering, then unlinks tmp. The test suite (tests/test_phase0_acceptance_canary.py:221,601) hashes the main file before and after and pins sha256 `42b6dad8…`. I probed a default-bound app: the main file hash was unchanged, but reading the WAL-mode evidence file created `runs.sqlite-shm` and `-wal` beside it. The frozen tree now shows those sidecars and `app.sqlite`. They come from the concurrent test process, not from my probes.

**Seeding race.** A 3-process cold seed repeated 40 times gave 120 `seed-ok` and no leftover tmp files. The residual windows are a crash between mkstemp and unlink (leaves a hidden tmp), an existing zero-byte or stale target (never re-seeded), and a filesystem without hardlinks (raw `OSError` escapes the lifespan).

**Migration.** `migrate` (db.py:391-453) is additive and idempotent when run sequentially. It runs `CREATE IF NOT EXISTS`, 9 guarded `ALTER TABLE evaluation_jobs ADD COLUMN`, a guarded `ALTER TABLE runs ADD COLUMN job_id`, and an `INSERT OR IGNORE` settings row. There is no schema-version tracking (no `user_version`). Shape is detected by `PRAGMA table_info` and `index_list`. It fails closed with `RuntimeError` on missing required columns or non-unconditional identity keys. Master's destructive DROP-and-recreate is gone. The evidence DB already carries OLD-shape app tables, so every seeded copy takes the ALTER path. It is NOT concurrency-safe: 4 concurrent `migrate()` on a fresh seed gave 77 of 160 `duplicate column name` errors.

**Projections.** Master hard-coded `MODELS` (examples/report_combined.py:27-34, used at store_load.py:127,147,186) and loaded stores once at startup. ATLAS uses `disk.agents()`, which is `SELECT DISTINCT agent FROM runs`, inside a per-request `open_projection` (projection.py:34-64). There is no cache. A brand-new model appeared without restart in both my probe and the live-projection test.

**Task versions.** The only guard is a refusal in store_load.py:168-178. Any (agent, task) cell with more than one `task_version` raises `ValueError`, which becomes a 503 on ALL aggregate endpoints. Nothing else looks at versions. Different agents on different versions of one task are pooled silently.

### Guarantees (claim / evidence / proven-by / confidence)

- **The default runtime DB is reports/app.sqlite, and reports/runs.sqlite is never selected implicitly. An explicit binding beats AFA_DB_PATH.**  
  evidence: afa_api/db.py:34,39-50; afa_api/main.py:44; afa_api/projection.py:28-30  
  proven by: tests/test_phase0_live_projection.py::test_same_running_app_discovers_new_model_and_stays_on_bound_db (explicit over env only). Default resolution has no test. I confirmed it with a probe.  
  confidence: `verified`
- **The API and worker refuse to open the evidence DB writable through afa_api.db, including via a symlink or hardlink alias. connect, ensure_working_db and migrate all raise ValueError.**  
  evidence: afa_api/db.py:53-73,176,207,379-388  
  proven by: tests/test_phase0_live_projection.py::test_runtime_rejects_evidence_aliases_but_offline_report_reads_them (EVIDENCE_DB_PATH monkeypatched to a tmp file)  
  confidence: `verified`
- **Projection reads use a genuine mode=ro URI and never silently fall back to a writable connection. A missing file raises and creates nothing.**  
  evidence: afa_api/db.py:183-195; runner/afa_runner/store.py:124-129  
  proven by: tests/test_phase0_live_projection.py::test_readonly_sources_cannot_create_or_write_databases  
  confidence: `verified`
- **Working-DB seeding is a coherent snapshot (backup API, WAL-inclusive) published no-clobber by hardlink. A concurrent winner is preserved and tmp files are cleaned up.**  
  evidence: afa_api/db.py:198-247  
  proven by: test_seed_snapshot_is_coherent_and_never_clobbers_a_winner. It simulates the race by monkeypatching os.link, not with real concurrency. My 3-process x 40 probe also passed.  
  confidence: `verified`
- **Migration is additive and idempotent when run sequentially. Existing rows are untouched. An unrecognized or populated app-table shape is refused, not dropped, and job/settings routes return 503.**  
  evidence: afa_api/db.py:330-347,391-453; afa_api/main.py:123-137  
  proven by: tests/test_a2_boundaries.py::test_migration_refusal_preserves_data_and_guards_control_routes; ::test_migration_rejects_trial_identity_without_rewriting_rows; ::test_repeated_populated_migration_preserves_app_facts  
  confidence: `verified`
- **Model roster, leaderboard, overview, meta and export are rebuilt per request from the bound DB, with no cache and no hard-coded model list. A new agent in the DB appears without restart.**  
  evidence: afa_api/projection.py:34-64; afa_api/store_load.py:141-143; runner/afa_runner/store.py:339-344  
  proven by: tests/test_phase0_live_projection.py::test_same_running_app_discovers_new_model_and_stays_on_bound_db. It uses a mock backend and a second DB as a sentinel that must not leak in.  
  confidence: `verified`
- **Any (agent, task) cell with more than one task_version makes every aggregate projection and healthz report a mixed-version refusal, returned as 503 with the exact ValueError text. /runs/{id} and /jobs are unaffected.**  
  evidence: afa_api/store_load.py:168-178; afa_api/projection.py:51-54; afa_api/routes_readonly.py:29-45,105-118  
  proven by: tests/test_api_readonly.py::test_mixed_version_refusal_surfaces_as_503. It injects one v2.0.0 row into a copied DB. I also probed it live.  
  confidence: `verified`
- **The exact-forensic route GET /runs/{id} reads via the read-only path and works even when the control plane or aggregates are refused.**  
  evidence: afa_api/routes_readonly.py:105-118; afa_api/serialize.py:370-378  
  proven by: tests/test_a2_boundaries.py::test_migration_refusal_preserves_data_and_guards_control_routes (asserts 404 for a missing id only)  
  confidence: `verified`
- **The main file of reports/runs.sqlite is not modified by the app or the canary. The canary asserts sha256 42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced before and after.**  
  evidence: tests/test_phase0_acceptance_canary.py:221,601-602  
  proven by: tests/test_phase0_acceptance_canary.py::test_phase0_acceptance_canary_real_api_offline. The app is bound to a tmp copy there, so the test proves little about the app; it mainly pins the file content.  
  confidence: `verified`

### Schema / state facts

- Evidence DB (reports/runs.sqlite @1e1a788): journal_mode=WAL in the header (bytes 18-19 = 2); 720 runs = 6 agents x 120 over 24 tasks; task_versions 1.0.0 (120 runs, 4 tasks), 1.0.1 (510 runs, 17 tasks), 1.0.2 (90 runs, 3 tasks); 0 mixed (agent, task) cells.
- Evidence DB already contains app tables in OLD shape: evaluation_jobs (no mode, source_evaluation_id, snapshot_json, owner_token or owner_started_at), job_events, app_settings and job_runs (all empty; settings_json='{}'), plus runs.job_id. It is not raw-layer-only, and every seeded copy takes the ALTER path.
- Working DB = <ROOT>/reports/app.sqlite (gitignored via reports/* and *.sqlite), mode 0600 from mkstemp, then WAL. Sidecars app.sqlite-shm/-wal are created. Seed tmp files are `.app.sqlite.seed-*.tmp`.
- Raw schema (runner SQLITE_SCHEMA): runs (with job_id TEXT at store.py:60), run_scores PK (run_id, formula_version), diffs, test_results. There is NO unique constraint on runs (agent, task_id, idx).
- App schema (db.py:85-158): evaluation_jobs (+ mode, source_evaluation_id, snapshot_json, owner_token, owner_started_at), job_events UNIQUE(job_id, seq), app_settings CHECK(id=1), job_runs PK(job_id, run_id), and evaluation_trials PK(evaluation_id, task_id, idx) carrying task_version and task_digest.
- No schema-version marker anywhere. jobs.py:257 schema_version is inside snapshot JSON, not the DB schema.
- app.state keys: db_path, migrate_error, auto_dispatch, agent_factory. The stores, load_error and cached-store keys of master are removed.
- Endpoints: /api/v1/{healthz,overview,leaderboard,domains/{agent},cell/{agent}/{task},run/{agent}/{task}/{idx},runs/{id},meta,export}. Tuple /run returns 409 with ambiguous=true when several rows share (agent, task, idx). Middleware migration_guard returns 503 on /jobs*, /settings and /reports/regenerate when migrate_error is set.
- current_version per task = tasks/<dir>/task.json 'version' (default '1.0.0'), read on each projection. The manifest has 0/24 'version' keys (report_combined.py:48-57). Synthetic oracle/noop rows are stamped with it, N=5 per task.
- In ATLAS, evaluated_versions equals current_version for all 24 tasks (probe: 0 mismatches).
- Read-only opens of the WAL evidence file create runs.sqlite-shm and runs.sqlite-wal (0 bytes) beside it; the main file hash is unchanged. Observed in the probe copy and in the frozen tree.

### Limitations and suspicious behaviour

- **[high] Migration is not concurrency-safe: check-then-ALTER (`_column_exists`, then `ALTER TABLE`) with no lock, and executescript/ALTERs are not one transaction. Probe: 4 simultaneous migrate() on a fresh seed gave 77 of 160 `OperationalError: duplicate column name` (owner_token, snapshot_json, owner_started_at, source_evaluation_id, mode). Consequences: the API sets migrate_error and control routes and all projections return 503 until restart with no retry; the worker crashes in serve(); a dispatch thread dies. afa_app.py starts the worker (line 120) before uvicorn (line 132), and both migrate the just-seeded DB; that this overlap happens in practice is inferred, not observed. docker-compose serialises via depends_on: api healthy.**  
  evidence: afa_api/db.py:417-431,410; afa_api/main.py:52-60; afa_api/worker.py:474-479; afa_app.py:113-126  
  integration relevance: Any merged subsystem that adds columns or tables via this migrate() reopens the window. Migrations from both sides should share one idempotent, lock-guarded (BEGIN IMMEDIATE) or try/except duplicate-column path.
- **[high] Mixed-version refusal is global and per (agent, task) only. One cell with two task_versions blacks out overview, leaderboard, domains, cell, meta, export and healthz for every agent. Across agents, different versions of the same task are pooled with no check. Probe: brand-new:1b at 9.9.9 was ranked with 1.0.0 agents in the task leaderboard. The kernel report functions have no version awareness; the only trace is meta.evaluated_versions.**  
  evidence: afa_api/store_load.py:149-178; runner/afa_runner/report.py:26-65 (no task_version reference); afa_api/serialize.py:152, 381-405  
  integration relevance: ORACLE bumped 18 task versions. In ATLAS alone evaluated equals current for all 24 tasks, so meta shows no mismatch. After the merge, current_version for 18 tasks will differ from the 1.0.x history, and that shows only as a notice in meta and the report subtitle. The first new app evaluation of an existing agent on a bumped task lands the same (agent, task) at a new version, which triggers the global 503. Cross-agent pooling would silently mix old and new versions. Whether version-aware projection or filtering is added on merge decides all of this.
- **[medium] Docstring vs code, evidence-bound startup: main.py:48-50 says that if migrate or recovery refuses the DB, control routes stay fail-closed while raw reads still work. But `ensure_working_db(db_path)` (main.py:46) sits outside the try block (lines 52-60). Binding the evidence path (app.state.db_path or AFA_DB_PATH) makes the lifespan raise ValueError and the app fails to start; no 503 mode exists for that case. Probe: `ValueError: refusing to open the immutable evidence database`. The same applies to the Docker images: api.Dockerfile:33 and worker.Dockerfile:28 still bake AFA_DB_PATH=/app/reports/runs.sqlite, and only compose overrides it.**  
  evidence: afa_api/main.py:44-60; docker/api.Dockerfile:33; docker/worker.Dockerfile:28; docker-compose.yml:23,58  
  integration relevance: A merged config or docs that point AFA_DB_PATH at the evidence file will crash at startup rather than degrade.
- **[medium] Fail-open and silent paths. (a) `ensure_working_db` returns silently when the evidence file is absent (db.py:209); `connect` and `migrate` then create an empty DB and healthz reports ok with an empty roster. (b) `_guard_migration_target` swallows sqlite3.Error and skips the check (db.py:381-384). (c) A zero-byte or stale existing target is never re-seeded. (d) A working DB is never refreshed or versioned against the evidence, so if evidence changes an existing app.sqlite stays stale with no detection.**  
  evidence: afa_api/db.py:198-212,379-388  
  integration relevance: If the merge changes or re-derives runs.sqlite (e.g. task-version bumps or re-graded evidence), an existing reports/app.sqlite will not pick it up. Old and new working DBs will silently diverge.
- **[medium] The evidence guard exists only at afa_api.db boundaries. The runner's SqliteRunStore(path) has no guard and runs executescript(SQLITE_SCHEMA) on open. examples/eval_persist.py:37,49 defaults to reports/runs.sqlite and writes it through the runner store. tests/test_api_readonly.py:102 opens the evidence file writable via SqliteRunStore (no data written, but it is how WAL sidecars appear). worker.serve does `afa.SqliteRunStore(db_path).close()` (worker.py:476).**  
  evidence: runner/afa_runner/store.py:130-136; examples/eval_persist.py:37,49; tests/test_api_readonly.py:102  
  integration relevance: Offline scripts, including any ORACLE tooling, can mutate evidence with no guard.
- **[low] POST /reports/regenerate writes report_combined.OUTPUT = reports/leaderboard.html, a git-tracked file (.gitignore whitelists it), using the working DB, so it now includes app-job runs.**  
  evidence: afa_api/routes_jobs.py:389-413; examples/report_combined.py:30-31; .gitignore  
  integration relevance: The committed leaderboard.html can drift from committed evidence. A merged report or integrity subsystem that treats it as reproducible from runs.sqlite could conflict.
- **[medium] Duplicate (agent, task, idx) rows are allowed (no unique constraint on runs; fresh independent evaluations are intended). Leaderboard and cell pool all of them. Probe: n 5 became 6 and the tuple route /run returned 409 ambiguous. Every runs.agent value, including mock or test job models, becomes a leaderboard 'real model'.**  
  evidence: afa_api/serialize.py:289-312; runner/afa_runner/store.py:275-340; runner/afa_runner/report.py:47-66; afa_api/db.py:133-135 (comment)  
  integration relevance: Repeat evaluations of a task at a new version double-count pooled results unless the merged code filters by version or evaluation.
- **[low] Cost and consistency of per-request projection. Each request, including healthz, loads all runs into two in-memory stores, adds 240 synthetic rows and reads all 24 task.json files. The disk reads (agents, per-agent load_runs, summary) are separate statements with no enclosing read transaction, so a concurrent worker commit can produce a torn view. The raw connection is a second snapshot. Docker healthcheck accepts 200 'degraded'.**  
  evidence: afa_api/store_load.py:141-163; afa_api/projection.py:45-58; afa_api/routes_readonly.py:46-58  
  integration relevance: A larger merged dataset scales linearly per request. No cache or single-snapshot semantics.
- **[info] Stale docstrings and comments. db.py:3-6 says the runner is untouched and frozen, but store.py changed materially: SQLITE_SCHEMA gains job_id, and it gains read-only mode, borrowed connections and savepoints. serialize.py:414 says 'never runs.id', contradicting /runs/{id} and 409 ambiguous. tests/test_api_readonly.py:19-22 says stores are loaded once. The db.py:11-14 docstring is stale about 'guarded' schema handling; the name `_heal_stale_app_tables` is now validation only. `ensure_schema_once` is dead code.**  
  evidence: afa_api/db.py:3-6,350-376,456-469; afa_api/serialize.py:414; tests/test_api_readonly.py:19-22  
  integration relevance: None functionally, but prose cannot be used as a source of truth.
- **[low] Backward-compat change vs master. An old-shape app table that lacks required columns (e.g. evaluation_jobs without cancel_requested) was auto-dropped and recreated on master. It is now refused with RuntimeError, so migrate_error is set and ALL projections plus control routes return 503, not only jobs. evaluation_trials has no forward-upgrade path: an older shape is refused. Unknown extra columns or tables pass silently.**  
  evidence: afa_api/db.py:330-376,437-447; projection.py:41-43; git diff fd423ab..1e1a788 -- afa_api/db.py  
  integration relevance: A DB from a merged variant with extra or renamed app-table columns will either be silently accepted (extras) or hard-refuse (missing).
- **[low] Connection details. `_apply_pragmas` sets journal_mode=WAL before busy_timeout, so the WAL switch can hit BUSY with no wait. An explicit empty db path falls back to env or default. A relative AFA_DB_PATH resolves against each process's cwd. ensure_working_db creates the file with mode 0600, which matters if the api and worker run as different users (inferred, not tested).**  
  evidence: afa_api/db.py:161-166,46-50,217-222  
  integration relevance: None specific, but processes could bind different DB files if cwd or env differ.
- **[medium] The canary pins the evidence content: sha256 42b6dad85ee6… is hard-coded and asserted before and after.**  
  evidence: tests/test_phase0_acceptance_canary.py:601-602  
  integration relevance: Any merged change that touches reports/runs.sqlite (rebuilt or re-graded evidence, version restamping) fails this canary even if the behaviour is correct.

### Integration assumptions

- reports/runs.sqlite is committed, immutable, WAL-mode, and holds 720 runs across 24 tasks with at most one task_version per (agent, task). Old-shape empty app tables and runs.job_id are already in it. Tests assert its exact sha256.
- tasks/<dir>/task.json 'version' is the single source of current_version. tasks/manifest.json has no 'version' key. The projection reads it on every request.
- One task_version per (agent, task) within a working DB. Runs at a different version for the same cell are treated as an error (503), not as a new generation.
- runs.agent is a free-form string, and every distinct value is a 'model' (or a leaderboard entry). Synthetic bookends are separate agents and are stamped at the current version.
- No unique key on runs (agent, task_id, idx). Duplicates are pooled. The evaluation-scoped tables (evaluation_trials) are what disambiguates them.
- Exactly one process migrates at a time, or migrate is only ever re-run against an already up-to-date schema. Nothing serialises the API and worker migrations.
- The evidence directory is writable (a mode=ro open of a WAL DB needs -shm and -wal) and the filesystem supports hardlinks for seeding.
- The api and worker share reports/app.sqlite and the same OS user (mkstemp creates it 0600). The launcher passes the same path to both.
- Kernel report functions (task_aggregate, leaderboard, domain_profile) are version-blind. Any per-version isolation must come from filtering runs before they enter the in-memory stores.
- The working DB is created once from evidence and never re-synchronised. New evidence must reach it by an explicit action.

### Open questions

- Does the launcher-time overlap between the worker's migrate and the API's migrate actually occur on first run? I forced the collision but did not observe it in afa_app.py itself.
- Does the merge intend to change reports/runs.sqlite (e.g. restamp task_version)? If so, it breaks the pinned canary hash and the 'one version per cell' assumption, and it means an existing app.sqlite is stale.
- Should new evaluations of a bumped task be allowed into the same working DB as older-version runs, and should projections filter by current version or refuse globally? ATLAS refuses only the same-agent mix, and pools silently across agents.
- On a read-only reports/ directory or a hardlink-less mount, does seeding fail the whole app at startup? I inferred this and did not test it.
- Is the 0600 mode of app.sqlite a problem when Docker api and worker run as different UIDs? Not tested.
- What clears a persistent migrate_error after a transient migration failure? Nothing in the code does; a restart is needed. Is that acceptable?

---

## ATLAS Phase-0 acceptance canary + ATLAS test inventory (frozen 1e1a788)

**Canary** (tests/test_phase0_acceptance_canary.py, 1 test, 9.17s in baseline log). REAL: a sqlite copy of reports/runs.sqlite (shutil.copy :223), the real FastAPI app driven by an in-process ASGI TestClient (no socket, no HTTP server), real dispatch_job threads (worker.py dispatch_job), a real fcntl owner lock (jobs.py:83-105), and real LocalSandbox subprocess grading via run_once. FAKED: mock_agent_factory overlays reference/ files (worker.py:41-55). The interruption is a BaseException raised from act() (:273), which escapes run_once's `except Exception` (pipeline.py:101) and the worker's `except Exception`. Thread death is swallowed by a monkeypatched threading.excepthook (:242). The lock is freed by run_job's finally, so the trial stays `claimed` and the job stays `running`. No clocks are faked. "Restart" is create_app() plus a new TestClient in the same process (:483, :564); module globals such as _ACTIVE_OWNER_LOCKS survive it. Only a3:1134 and a3:1309 kill real processes.

Stages: A :332-361, live discovery :348-361, B :365-398, C reuse :407-446, D interrupted :452-478. Then cancel and recovery, resume, only idx 1 executes (:509), reports/results/forensics equality after restart (:564-591), historical SHA (:601-603). Recovery works as follows: the cancel flag is set while the job is still `running`. On startup reclaim_stale_running(recover_unlocked=True) requeues it, the lifespan redispatches it, and the worker sees cancel_requested before creating any agent. That is why recovery_attempts == [] and the job ends `canceled`.

Task: hard-coded id "fix-binary-search" (:16), resolved from db.ROOT/tasks/<id> by jobs.task_snapshot (jobs.py:197-217). The task version and digest are not hard-coded; assertions read them from report["task_snapshots"] (:199, :355). Historical SHA: sha256 of the main file of db.DB_PATH = reports/runs.sqlite, before and after. It is also compared to the literal 42b6dad8... at :602, which matches both the working file and `git show HEAD:` (WAL sidecars excluded). The check is weak: the app is bound to the copy, so only code that writes to the evidence path would trip it. The literal is checked last, after everything else passes.

**Integration-critical fragility** (ORACLE change -> ATLAS line):
- Any byte change to reports/runs.sqlite -> canary:602.
- A version bump of fix-binary-search -> live_projection:183, then :205 (a synthetic "1.0.0" row plus a live-version row gives a mixed cell, so /overview returns 503, store_load.py:168-178). Also a2:335 and tests/test_api_readonly.py:221-222, 238, 268-269. The last are master files.
- A task added or removed -> the `== 24` and 720 constants in both test_api_readonly files.
- Any file added under tasks/<id>/ -> the digest changes (_task_digest, jobs.py:185-194, rglob over every file). Resume and reuse then refuse, but only if the file changes between create and resume.

**Baseline**: the full suite passed 493, and all in-scope groups pass. There are no skip/xfail markers and no conftest. Real network: a2:482 (loopback, port 0). Real processes: a3:1134 and a3:1309 (SIGKILL, 10s deadlines). Nothing else uses sockets.

**Gaps**: no real-crash test inside the save_run -> complete_trial -> commit window (only injected exceptions). Every test uses a single task, so multi-task drift and blocking is untested. No test re-evaluates an already-historical agent name after a version bump, which is the post-merge scenario that would 503 every projection. fcntl is POSIX-only and the lock is same-host only.

Disclosure: I ran one read-only `sqlite3 SELECT` on frozen reports/runs.sqlite. The main file's SHA is unchanged (42b6dad8...). The header is WAL mode, so -shm and a 0-byte -wal sidecar were touched. These are gitignored.

### Guarantees (claim / evidence / proven-by / confidence)

- **A fresh evaluation of identical params creates a new evaluation ID and new raw runs rows; no global skip of existing runs.**  
  evidence: afa_api/jobs.py:304-440 (uuid job_id, trials inserted pending/missing); afa_api/worker.py:_run_job_locked trial loop (~:233-330) only skips trials that are 'completed' within the same evaluation  
  proven by: tests/test_phase0_acceptance_canary.py::test_phase0_acceptance_canary_real_api_offline (A vs B disjoint run IDs :375); tests/test_evaluation_identity.py::test_default_evaluations_are_fresh_and_raw_ids_are_distinct; tests/test_jobs_api.py::test_same_parameters_are_fresh_and_not_reused  
  confidence: `verified`
- **Explicit reuse mode creates zero new raw rows. Trials point at the source's run IDs, with source_evaluation_id, source_run_id and origin_evaluation_id (preserved across reuse chains) and evidence_state='reused' / comparability='provisional'. Reuse is refused if the source snapshot (model, backend, generation, tasks incl. version and digest, repeats) differs from the current snapshot built from disk, or if the source's evidence is incomplete or of unknown origin. Refusal is atomic.**  
  evidence: afa_api/jobs.py:304-440 (_snapshot_identity compare :317; eligibility gates :325-360); jobs.py:trial_detail comparability ~:660-668  
  proven by: canary :407-446 (C: raw id list unchanged, reused trials, provisional); tests/test_evaluation_identity.py::test_explicit_reuse_has_source_and_origin_without_new_raw_rows; tests/test_a3_boundaries.py::test_reuse_rejects_each_incompatible_snapshot_identity_atomically[5 params], ::test_reuse_rejects_new_eligibility_gates_without_logical_changes[4], ::test_reuse_chain_keeps_immediate_source_and_original_origin_without_execution, ::test_reuse_rejects_legacy_source_without_creating_any_rows; tests/test_a2_boundaries.py::test_reuse_rejection_is_all_or_nothing  
  confidence: `verified`
- **Same-ID resume executes only the pending trials. A completed trial keeps its original run_id, gets a 'run_skipped' event, and its agent is never invoked. The seed for a position is base_seed+idx.**  
  evidence: afa_api/worker.py:_run_job_locked (completed-trial branch ~:238-252; _set_effective_seed(agent, base_seed+idx)); afa_api/jobs.py:resume_job :836-873  
  proven by: canary :498-511 (resumed_attempts == [{idx:1, seed:1001}] via a tracking factory, first_d_run preserved :511); tests/test_evaluation_identity.py::test_resume_keeps_committed_trial_and_runs_only_pending; tests/test_a2_boundaries.py::test_http_resume_preserves_completed_evidence_and_id  
  confidence: `verified`
- **A raw run, its scores/diff/test_results, the job_runs link and the trial completion commit in one transaction (borrowed connection, save_run(commit=False)). Injected failures roll back all of it and leave the trial 'pending' with the claim released.**  
  evidence: afa_api/worker.py:_run_job_locked ~:295-322 (store.save_run(commit=False); complete_trial; conn.commit(); except: rollback + _release_claim); runner/afa_runner/store.py save_run/close (borrowed conn not closed)  
  proven by: tests/test_evaluation_identity.py::test_raw_trial_transaction_rolls_back_together; tests/test_a3_boundaries.py::test_worker_failure_rolls_back_raw_score_diff_test_link_and_trial, ::test_worker_association_failure_rolls_back_all_evidence_components, ::test_commit_false_late_raw_save_rolls_back_every_component_and_preserves_caller_work[2]. Failures are injected Python exceptions, not process crashes.  
  confidence: `read-only-inferred`
- **A running evaluation with a live owner (held OS flock) is never reclaimed even with an aged lease. An owner whose lock is free (process killed) is reclaimed at startup with recover_unlocked=True, its 'claimed' trials go back to pending, and a stale owner token cannot complete a trial or terminalize the job (fencing).**  
  evidence: afa_api/jobs.py:83-105 (flock LOCK_EX|LOCK_NB + _ACTIVE_OWNER_LOCKS), :749-833 (reclaim_stale_running), :493-536 (complete_trial fenced by claim_token and owner_token), :903-935 (mark_terminal fenced); afa_api/main.py:lifespan  
  proven by: tests/test_a2_boundaries.py::test_live_owner_lock_protects_and_startup_recovers_before_lease_expiry, ::test_successor_fences_old_trial_and_terminal_mutations, ::test_api_startup_does_not_reclaim_live_owner, ::test_api_startup_reclaims_unlocked_running_work; tests/test_a3_boundaries.py::test_standalone_process_restart_preserves_completed_trial_and_cancel_state and ::test_registered_api_lifespan_dispatches_an_interrupted_trial (real subprocess + SIGKILL); ::test_registered_api_dispatch_and_startup_protect_an_aged_owner; the canary covers only the in-process variant  
  confidence: `verified`
- **Cancel is a flag while running and is honoured only at the next trial boundary. Auto-recovery of an interrupted job with cancel_requested=1 terminalizes it as 'canceled' without executing anything, and only an explicit resume clears the flag.**  
  evidence: afa_api/jobs.py:876-893 (request_cancel), :836-873 (resume_job sets cancel_requested=0); afa_api/worker.py cancel checks before each pending trial and at the end  
  proven by: canary :473-509; tests/test_a3_boundaries.py::test_standalone_process_restart_preserves_completed_trial_and_cancel_state (real processes); tests/test_jobs_api.py::test_cancel_running_job_is_honored_between_runs (only cancel-before-first-run); tests/test_a3_boundaries.py::test_cancel_claim_race_flags_the_actual_running_state  
  confidence: `verified`
- **Resume, and per-trial execution, refuse when the current task version or the recursive task-dir digest differs from the creation snapshot. The affected trials become blocked/unverifiable, and a resume after byte-exact restoration reopens only the blocked positions. Reuse refuses if the current disk snapshot differs from the source snapshot.**  
  evidence: afa_api/jobs.py:185-236 (_task_digest, task_snapshot, validate_snapshot_tasks); afa_api/worker.py:_load_snapshot_task ~:120-134; jobs.py:resume_job resets blocked->pending  
  proven by: tests/test_a2_boundaries.py::test_resume_rejects_real_task_pack_drift (version 9.9.9 in a tmp copy of the task); tests/test_a3_boundaries.py::test_restored_snapshot_resume_reopens_only_blocked_positions; tests/test_evaluation_identity.py::test_changed_task_snapshot_is_unverifiable_not_drifted (monkeypatches jobs.task_snapshot, so the digest logic itself is stubbed)  
  confidence: `verified`
- **The immutable evidence DB (reports/runs.sqlite, incl. symlink aliases) is refused as a writable runtime DB by connect/migrate/ensure_working_db. Seeding a working copy uses the SQLite backup API plus no-clobber os.link. Read-only connections cannot create or write.**  
  evidence: afa_api/db.py:26-72 (assert_writable_runtime_path), :198-248 (ensure_working_db)  
  proven by: tests/test_phase0_live_projection.py::test_runtime_rejects_evidence_aliases_but_offline_report_reads_them, ::test_seed_snapshot_is_coherent_and_never_clobbers_a_winner, ::test_readonly_sources_cannot_create_or_write_databases. The canary's historical-SHA check adds little because the app is never pointed at the evidence file.  
  confidence: `read-only-inferred`
- **Projection endpoints (overview, cell, domains, leaderboard, export, report regenerate) are built per request from the bound working DB, so a post-startup write by a new model is visible with no restart.**  
  evidence: afa_api/main.py:lifespan comment; afa_api/store_load.py:load_stores (fresh :memory: aggregation each call); afa_api/projection.py  
  proven by: tests/test_phase0_live_projection.py::test_same_running_app_discovers_new_model_and_stays_on_bound_db (asserts absence before, presence after; the canary asserts presence only, :348-361); canary :348-361  
  confidence: `verified`
- **Any (agent, task) cell containing more than one task_version makes every aggregate projection refuse (HTTP 503 on read routes, 409 on /reports/regenerate) instead of pooling. Exact raw run reads (/api/v1/runs/{id}) still work.**  
  evidence: afa_api/store_load.py:168-178; afa_api/routes_readonly.py:40-42; afa_api/routes_jobs.py:391-404 (409 for ValueError, 503 for OSError/sqlite3.Error; the docstring matches the code)  
  proven by: tests/test_evaluation_identity.py::test_exact_run_route_and_ambiguous_tuple_route (503 after forcing 'unrelated-version'); tests/test_api_readonly.py mixed-version test (master file)  
  confidence: `verified`
- **A durable per-evaluation report (JSON + Markdown) is deterministic, scoped to the evaluation's own trials, byte-identical after an app re-creation, and reports missing, partial or unavailable artifacts explicitly instead of inventing values. Comparability is emitted only when patch and test_results both exist, and only for fresh (comparable) or reused (provisional) evidence.**  
  evidence: afa_api/evaluation_report.py:build_evaluation_report/render_markdown; afa_api/jobs.py:trial_detail :600-668; afa_api/routes_jobs.py:report routes use connect_readonly  
  proven by: tests/test_evaluation_reports.py (8 tests, esp. ::test_reports_are_scoped_deterministic_and_survive_app_reopen, ::test_reports_show_partial_missing_and_unverifiable_artifacts, ::test_report_does_not_invent_defaults_for_invalid_persisted_params, ::test_report_routes_use_readonly_connections); tests/test_a3_boundaries.py::test_trial_detail_does_not_claim_complete_or_comparable_without_test_artifacts; canary :385-395, :564-587  
  confidence: `verified`
- **Migration is additive and idempotent, and fails closed with data preserved on an unsupported pre-existing app schema. The control-plane routes then return 503 while exact raw-run reads keep working.**  
  evidence: afa_api/db.py:280-450 (unique-identity and column checks, messages 'unsupported existing ... schema'); afa_api/main.py migration_guard  
  proven by: tests/test_evaluation_identity.py::test_empty_migration_and_malformed_app_schema_fail_closed; tests/test_a2_boundaries.py::test_migration_refusal_preserves_data_and_guards_control_routes, ::test_migration_rejects_trial_identity_without_rewriting_rows, ::test_repeated_populated_migration_preserves_app_facts; tests/test_a3_boundaries.py::test_migration_rejects_partial_or_missing_app_identity_before_mutation[5], ::test_legacy_raw_forensics_survive_control_plane_migration_refusal  
  confidence: `verified`
- **Baseline run of ATLAS 1e1a788: the full suite passes (493 passed, 363.5s). Groups: 01=14, 02=24, 03=12, 04=8, 05=15, 06=18, 07=14, 08=34, 09=1; historical SHA unchanged before and after (canary receipt).**  
  evidence: ../atlas_baseline/summary.txt, 10_FULL_SUITE.log, 09_canary_receipt.log  
  proven by: n/a (execution log)  
  confidence: `verified`

### Schema / state facts

- Evidence DB constant: db.EVIDENCE_DB_PATH = ROOT/reports/runs.sqlite; db.DB_PATH is a legacy alias for it (afa_api/db.py:33-35). The default working DB is reports/app.sqlite (:34); AFA_DB_PATH overrides it and an explicit app.state.db_path beats both (:41-54).
- The committed reports/runs.sqlite is git-tracked (last changed in fd423ab), sha256 42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced, header bytes 18-19 = 02 02 (WAL). It holds 24 tasks with 30 runs each, at exactly the current task.json versions.
- Tables: evaluation_jobs (PK id; status; cancel_requested; params_json; counters; mode; source_evaluation_id; snapshot_json; owner_token; owner_started_at), db.py:~63-90. job_events UNIQUE(job_id, seq) :115. job_runs PK (job_id, run_id) :127. evaluation_trials PK (evaluation_id, task_id, idx) :136-153. app_settings. runs.job_id is a nullable added column.
- evaluation_trials.trial_state in {pending, claimed, completed, blocked}. evidence_state in {missing, fresh, reused, unverifiable}. Job status in {queued, running, succeeded, failed, canceled}; job mode in {fresh, reuse, legacy}.
- Trial claim: pending->claimed sets a claim_token, guarded by the job status='running' and owner_token (jobs.py:472-490). complete_trial requires claim_token and owner_token (:493-536).
- Task snapshot per task: {task_id, task_version (task.json 'version'), task_digest ('sha256:' + sha256 over sorted relative-path + bytes of EVERY file under db.ROOT/tasks/<id>/)} (jobs.py:185-217). The snapshot also holds model, backend{kind, base_url}, generation{base_seed default 1000, temperature, timeout, provenance}, repeats.
- Owner lock file: <tempfile.gettempdir()>/agentforge-arena-evaluation-locks/<sha256(dbpath)[:24]>/<sha256(job_id)>.lock, fcntl.flock LOCK_EX|LOCK_NB, plus the in-process set _ACTIVE_OWNER_LOCKS (jobs.py:68-105). Locks are never deleted.
- Endpoints: POST /api/v1/jobs, GET /jobs/{id}, POST /jobs/{id}/cancel|resume|retry, GET /jobs/{id}/results|trials|report.json|report.md|events, GET /api/v1/runs/{run_id} (exact), GET /api/v1/run/{model}/{task}/{idx} (409 with candidate_run_ids when ambiguous), /overview, /cell, /domains, /leaderboard, /meta, /export, POST /reports/regenerate.
- Mixed-version refusal is keyed per (agent, task) (store_load.py:168-178), not per task. Synthetic ORACLE/NOOP baselines are tagged with the CURRENT task version in the 'full' store only (store_load.py:181-185).
- Reproducibility env of the grading sandbox includes PYTHONDONTWRITEBYTECODE=1 (sandbox.py:60). find tasks -name __pycache__ returned nothing after the baseline suite.
- Canary determinism inputs: model = 'phase0-canary-<uuid4 hex>', base_seed default 1000, repeats=2, backend mock. Baseline receipt: A=[1221,1222], B=[1223,1224], C=A's runs, D=[1225,1226].
- Test inventory (defs/collected): canary 1/1; live_projection 8/8; evaluation_identity 14/14; evaluation_reports 8/8; jobs_api 11/11; a2_boundaries 14/14; a3_boundaries 22/34 (parametrize adds 12: 5+2+4+5 over four functions); runner store 15/15; afa_api/tests/test_jobs 13/13. Log group 02 = 11+13 = 24 reconciles. Group 03 = 12 = 8 + probably 4 in runner/tests/test_report_combined.py (not verified from the log).

### Limitations and suspicious behaviour

- **[medium] The canary's 'historical DB SHA unchanged' check is weak. The app is bound to a tmp copy via app.state.db_path, so the check only catches code that writes to reports/runs.sqlite directly. The hash is of the main file only (no -wal/-shm), and the committed file is WAL-mode.**  
  evidence: tests/test_phase0_acceptance_canary.py:221-223, :324-326, :601-603; xxd of reports/runs.sqlite bytes 18-19 = 0202  
  integration relevance: After the merge the check protects nothing about ORACLE unless ORACLE writes to the evidence DB path. It also does not check that reports/app.sqlite (the default working DB) was left untouched.
- **[high] The historical hash is a hard-coded literal, checked last (:602), after every behavioural assertion has passed.**  
  evidence: tests/test_phase0_acceptance_canary.py:602  
  integration relevance: If ORACLE (or the merge) rewrites reports/runs.sqlite (re-grade, bumped task_version rows, checkpoint), this fails even though before == after. That would be a benign failure of the literal, not of ATLAS behaviour. Check before == after separately from the literal.
- **[medium] 'Restart', 'recovery' and 'another restart' in the canary are simulated by create_app() plus a new TestClient in the same OS process. There is no process death and no real HTTP. The mock backend is the only backend, and interruption is a BaseException raised from act().**  
  evidence: tests/test_phase0_acceptance_canary.py:265-273, :483-486, :564-570; only tests/test_a3_boundaries.py:1134 and :1309 use subprocess + SIGKILL  
  integration relevance: Real-crash and cross-process coverage lives in the a3 tests. A merge that changes worker.serve or lock semantics would show up in a3, not in the canary.
- **[low] The canary never asserts that the model is absent from /overview before A ('unknown runtime model' holds only by uuid naming). The live-discovery check asserts presence only, and the reuse check compares only the list of runs.id.**  
  evidence: tests/test_phase0_acceptance_canary.py:224, :348-361, :404-416; contrast tests/test_phase0_live_projection.py:124-126  
  integration relevance: None.
- **[high] live_projection test 1 mixes a worker-created run (live task version) with a synthetic run hard-coded to version '1.0.0' in the SAME (agent, task) cell.**  
  evidence: tests/test_phase0_live_projection.py:55, :183, :205-208 vs afa_api/store_load.py:168-178  
  integration relevance: If ORACLE bumps fix-binary-search above 1.0.0 (it is currently 1.0.0), this test fails with a 503 (and line 183 fails first). That is a benign test-assumption failure, not an ATLAS regression.
- **[high] tests/test_a2_boundaries.py:335 asserts the snapshot version of the live task equals '1.0.0'. The same literal appears in tests/test_api_readonly.py (master, unchanged by ATLAS): :221-222, :238, :268-269, plus EXPECTED_N_TASKS=24 / EXPECTED_TOTAL_RUNS=720 in that file and afa_api/tests/test_api_readonly.py:44-53.**  
  evidence: tests/test_a2_boundaries.py:335; tests/test_api_readonly.py:43-44, 167-169, 221-222, 238, 262-269; afa_api/tests/test_api_readonly.py:44-53  
  integration relevance: They break benignly if fix-binary-search is bumped, or if tasks/manifest.json or the historical DB row count change. 4 tasks are at 1.0.0 today (async-timeout, fix-binary-search, fix-roman-numerals, grid-paths); 17 are at 1.0.1 and 3 at 1.0.2.
- **[medium] _task_digest hashes every file (recursively, including dotfiles and caches) under tasks/<id>/. There is no ignore list.**  
  evidence: afa_api/jobs.py:185-194; used at create (:255), resume (:229), per trial (worker.py _load_snapshot_task), and reuse comparison (:317)  
  integration relevance: Any file ORACLE adds under tasks/*/ changes the digest. That is harmless if it is stable for the whole test, but a file that is generated or mutated at runtime, or a __pycache__/.DS_Store/lock file, would trigger 'changed since evaluation creation' refusals or blocked/unverifiable trials. Tests compute digests dynamically, so a static added file breaks no assertion.
- **[low] Task-pack verification is per trial start. A pack mutated during act() is not detected for the trial in flight; only the next trial blocks. The run row keeps the old snapshot version/digest even though grading reads the disk afterwards.**  
  evidence: afa_api/worker.py _run_job_locked (_load_snapshot_task before claim; run_once after); tests/test_a3_boundaries.py::test_restored_snapshot_resume_reopens_only_blocked_positions expects ['completed','blocked'] after mutating during act  
  integration relevance: None directly. If ORACLE re-verifies pack integrity at load or grade time, its behaviour and ATLAS's per-trial check could disagree.
- **[low] Reuse eligibility compares the trial's task_version/digest with the source snapshot and the current disk snapshot, but never checks the raw runs.task_version column of the reused run.**  
  evidence: afa_api/jobs.py:317-360 (trial_detail selects run_task_version but does not use it)  
  integration relevance: If ORACLE re-labels runs.task_version in the DB, ATLAS reuse and reports would not notice.
- **[info] test_jobs_api.py module docstring claims cancel is 'honored between runs with completed_runs frozen at the cancel point', but the test cancels BEFORE the first run (0 completed). The 1-completed mid-evaluation cancel is covered only by the canary and a3.**  
  evidence: tests/test_jobs_api.py:19-21 vs :284-310  
  integration relevance: None.
- **[info] db.py docstring says the live DB ships in journal_mode=delete, but the committed reports/runs.sqlite header says WAL (0202).**  
  evidence: afa_api/db.py:8-9 (docstring) vs xxd reports/runs.sqlite  
  integration relevance: Any reader may create -wal/-shm sidecars next to the evidence file (gitignored). A tool that checkpoints could change the main-file hash.
- **[low] Flakiness is bounded by wall-clock polls, with no faked clocks. The tightest budgets are tests/test_evaluation_reports.py wait_terminal (500x0.01s = 5s for 2 real graded runs), and a3's subprocess tests with 10s waits and SIGKILL. The canary allows 15s per wait; a2 and a3 use 5-10s Event timeouts.**  
  evidence: tests/test_evaluation_reports.py:41-46; tests/test_a3_boundaries.py:1134-1307, :1309-1460; baseline: canary 9.17s, a3 35.95s  
  integration relevance: If ORACLE adds per-run integrity work, or slows grading, timeout-only failures are a plausible false positive.
- **[info] Disclosure: during this audit I ran `sqlite3 reports/runs.sqlite 'select ...'` inside the frozen tree, a read-only query.**  
  evidence: Post-check: main-file sha256 still 42b6dad8... (equal to `git show HEAD:reports/runs.sqlite`); reports/runs.sqlite-shm and a 0-byte -wal exist (gitignored, WAL-mode header).  
  integration relevance: The main file is byte-identical. The sidecar mtimes may reflect my query and/or the concurrently running suite.

### Integration assumptions

- tasks/<id>/ is self-contained with task.json ('id' equal to the dir name, 'version'), snapshot/, reference/ and grading/. a2:315 and a3:278 copy ONLY tasks/fix-binary-search into a tmp root and monkeypatch db.ROOT and worker.TASKS_DIR. A load_task or an integrity layer that needs files outside the task dir (a global checksum registry, tasks/manifest.json) would break those two tests.
- The mock agent yields a passing run: reference/**/*.py is overlaid, giving status 'valid', score 1.0 and functional_pass=True. Asserted at jobs_api:161, reports ('Score: `1.0`'), canary (n_valid >= 2, patch_available, non-empty test_results). ORACLE hardening of grading or of task packs could turn the mock into a void or fail and break these.
- tasks/fix-binary-search/reference/searchkit/search.py exists at that path (a2:483).
- The evidence DB reports/runs.sqlite is byte-stable, and is a valid seed for the tests' shutil.copy (WAL header, rows at the current versions). Tests copy the file alone, without sidecars.
- task_version in the runs table is the task.json version at run time (worker loads the task and checks it against the snapshot). Tests assert dynamic equality of trial.task_version and runs.task_version (canary :179) but literal '1.0.0' in the places listed above.
- Mixed-version detection is per (agent, task). New model names avoid collisions with historical agents. A re-run of a historical agent name against a bumped task will 503 all aggregates.
- Python threads plus the fcntl file lock imply POSIX, same host, same TMPDIR. The subprocess tests build PYTHONPATH from the repo path, so the merged tree must keep kernel/, runner/, examples/ and afa_api/ importable from the repo root.
- The suite is not isolated from the repo tree: afa_api/tests/test_api_readonly.py uses the module-level default app, which creates reports/app.sqlite inside the repo. Reports go to reports/leaderboard.html unless monkeypatched. The full suite must run against a writable tree.
- afa_api.worker.dispatch_job and jobs.* are looked up as module attributes at call time, so tests can monkeypatch them (canary :250). A merge that changes call-by-reference imports would break the observer.

### Open questions

- Is fix-binary-search among the 18 tasks ORACLE bumped? It is one of only 4 tasks at 1.0.0. If yes, live_projection:183 and :205, a2:335 and both test_api_readonly files will fail benignly, and a merged canary still passes only if runs.sqlite is untouched.
- Does ORACLE modify reports/runs.sqlite (re-grade, add rows, change stored task_version)? If so canary:602, EXPECTED_TOTAL_RUNS=720 and the 'evaluated_versions' assertions (tests/test_api_readonly.py:269) all change together.
- Does ORACLE add files under tasks/*/ (checksum or lock files), and are any of them rewritten at runtime? That decides whether ATLAS's digest guard yields spurious 'changed since evaluation creation' refusals.
- Which files does baseline group 03_reports (12 passed) collect? The likely composition is tests/test_evaluation_reports.py (8) + runner/tests/test_report_combined.py (4 defs), inferred from counts and not read in the log.
- Nothing in the ATLAS tests covers a historical agent name re-evaluated after a task version bump (per-cell mixed refusal turning every projection into 503). Will ORACLE's version bumps make historical agents' cells mixed once ATLAS writes new runs for them?
- No test kills a process between save_run(commit=False) and the final commit. Is SQLite's atomicity assumed to hold, since only injected exceptions are tested?

---

## Completeness critic

### Claims found INCORRECT or OVERSTATED (with corrections)

- **[Live-projection/DB auditor (auditor 1)]** claim: 'The only guard is a refusal in store_load.py:168-178' for task versions; 'Nothing else looks at versions.'  
  **correction:** Overstated. A second identical per-cell refusal exists in examples/report_combined.py:159-169 (used by POST /reports/regenerate and the offline report), and the evaluation side also enforces version and digest checks on snapshots (jobs.py:220-236, worker.py:129-142). The aggregate-projection guard is only one of three version mechanisms.  
  evidence: examples/report_combined.py:159-169; jobs.py:220-236; worker.py:129-142
- **[Live-projection/DB auditor (auditor 1)]** claim: Docstring at main.py:48-50 is described merely as 'inconsistent' for the evidence-bound path.  
  **correction:** Sharper than reported: the fail-closed 503 mode applies only to migrate/recovery failures. ensure_working_db (main.py:46) sits outside the try (52-60), so an evidence-bound AFA_DB_PATH raises ValueError out of the lifespan and the app does not start. Both Dockerfiles bake that exact bad value as the image default.  
  evidence: afa_api/main.py:44-60; docker/api.Dockerfile:33; docker/worker.Dockerfile:28
- **[Trial/ownership auditors (2 and 3)]** claim: Version/digest drift semantics are described as 'unverifiable' at job level ('no verifiable evidence'), implying a distinct state.  
  **correction:** There is no distinct job status. Drift yields trial_state='blocked' with evidence_state='unverifiable' per task, and the job simply ends 'failed'. Also, blocked trials are iterated from a stale pre-fetched list, so remaining positions of the same task re-run the check and re-emit error events.  
  evidence: worker.py:270-306, 396-410; jobs.py:539-558
- **[Canary auditor (auditor 6)]** claim: 'The historical-SHA check is weak' but also that the literal is a HIGH-severity fragility.  
  **correction:** Both are true but the fragility is narrower. The literal is asserted on historical_before (line 602) and the before==after check is separate (603), so a benign evidence rewrite fails ONLY the literal. This means a merged rebuild of runs.sqlite fails the canary at the very end, after all behavioural assertions have passed.  
  evidence: tests/test_phase0_acceptance_canary.py:601-603
- **[Provider auditor (auditor 5)]** claim: Reuse compat / provenance: 'the snapshot labels seed provenance requested' and 'reports label missing pieces unavailable' rated read-only-inferred.  
  **correction:** Upgraded to verified for the snapshot side, since build_snapshot writes seed_provenance/timeout_provenance (jobs.py:256-272). The real gap is that provenance is 'requested' only: the seed is ignored by ollama (agents_openai.py:37 comment), and the runs row has no provider or backend column, so mock and real runs are indistinguishable in raw runs (worker.py:56-58 labels mock runs agent=<model>).  
  evidence: jobs.py:256-272; worker.py:56-58; agents_openai.py:37

### Topics no auditor covered adequately

- Read-transaction consistency across the request-time disk reads in load_stores (agents(), per-agent load_runs, summary run without an enclosing transaction; store_load.py:141-163). Auditor 1 noted it but nobody probed torn projections under a concurrent worker commit.
- Frontend (web/) handling of 503 and 'degraded' responses. Only a type definition exists, ATLAS changed no web/ files, and web tests hard-code model names (web/tests/*.spec.ts). Unverified whether the SPA's model list is fully dynamic.
- Whether ORACLE's runs.task_version restamping or bumps interact with the two independent version sources: evaluation_trials/snapshot vs runs.task_version. ATLAS never compares them. Nobody proposed a concrete guard or enumerated every reader (reports, reuse, trial_detail, aggregates) that trusts one or the other.
- Multi-score-row (run_scores formula_version) behaviour was probed only for /runs/{id} and trial_detail, not for refresh_counters, load_runs or the aggregates. It is relevant if ORACLE writes a second formula_version.
- Real-backend (ollama/openai_compat) end-to-end evaluation through the worker with a live unseen model. Only mock-backed E2E plus a loopback openai transport test exist (a2_boundaries); ollama_generate is never exercised by any test.
- Offline tooling paths bypassing the guard (examples/eval_persist.py defaulting to reports/runs.sqlite via the unguarded SqliteRunStore, runner store.py:130-136) were noted but not traced for every script that ORACLE tooling might reuse.
- Behavior of the app when the tasks/ directory content changes between API startup and requests (current_version is re-read per request from task.json, but the manifest, TASKS_DIR and db.ROOT are separate path sources); the path-consistency assumption was noted but not tested.

### Top integration risks (for a merge adding `tasks/*/integrity/`, bumping 18 task versions, adding `overlay_diff`)

1. **Version bump on 18 tasks meets historical runs, producing global 503 on first same-agent re-evaluation and silent cross-agent pooling**  
   why: The refusal is per (agent, task) and global (store_load.py:168-178): any historical agent name re-run on a bumped task makes overview, leaderboard, cell, domains, meta, export and healthz 503 as soon as the first run persists, and POST /reports/regenerate 409. A new model name evades the refusal but is then ranked against old-version agents with no marking (evaluated_versions vs current_version is a notice only). Today all 24 tasks have evaluated==current, so this is invisible pre-merge.  
   how to test: On a copy of the merged tree, seed app.sqlite from runs.sqlite, POST a mock job (model 'qwen3.5:9b' and a second, new model) on a bumped task, then GET /overview, /leaderboard, /meta and POST /reports/regenerate. Repeat with the new model only and inspect the task leaderboard for pooled versions.
2. **integrity/ files and task.json version edits change _task_digest (rglob over EVERY file, no exclusions) and version**  
   why: Any in-flight or pre-merge evaluation snapshot then fails resume ('changed since evaluation creation'), worker trials become blocked/unverifiable, and reuse from pre-merge sources is 'incompatible'. Only jobs._task_digest reads the dir; runner, grader and mock overlay ignore extra files, so execution is unaffected. Any non-deterministic or runtime-written file in integrity/ (timestamps, caches) would make digests unstable between snapshot and use.  
   how to test: Create a job on the merged tree, add/touch a file under tasks/<id>/integrity/, POST resume and run the worker: expect 409 and blocked trials. Also hash the dir twice around a run of the ORACLE tooling to confirm it is byte-stable. Test reuse with a pre-merge source.
3. **Pinned hash and hard-coded version/count literals in ATLAS tests break benignly**  
   why: tests/test_phase0_acceptance_canary.py:602 pins runs.sqlite sha256; test_phase0_live_projection.py:183,205 and test_a2_boundaries.py:335 and tests/test_api_readonly.py (EXPECTED 24 tasks, 720 runs, '1.0.0') hard-code fix-binary-search at 1.0.0 (one of 4 tasks at 1.0.0). If ORACLE bumps it or the merge rewrites runs.sqlite, failures are fixture-attribution noise rather than behaviour regressions. The live-projection test also builds a synthetic '1.0.0' row that becomes a mixed cell when the live version differs.  
   how to test: After merge, run tests/test_phase0_acceptance_canary.py, test_phase0_live_projection.py, test_a2_boundaries.py, tests/test_api_readonly.py and afa_api/tests/test_api_readonly.py first. Classify each failure by whether it is a literal (sha/version/count) or a behavioural assertion; check whether fix-binary-search is among the 18.
4. **overlay_diff() added to pipeline.py collides with ATLAS's RunRecord.run_id insertion and with the mock/reference overlay semantics**  
   why: overlay_diff does not exist in ATLAS (grep empty); pipeline.py already has _reference_diff/validate_task, and ATLAS edited only RunRecord (run_id inserted before grade_report, pipeline.py:45). Textual conflict is likely small, but any new positional RunRecord field or constructor change silently mis-binds. ATLAS's worker mock path (_read_reference_writes, worker.py:41-53) reproduces the reference overlay independently, so the two overlay implementations can diverge and mock evaluations persist as ordinary 'fresh/comparable' rows labelled with the model name.  
   how to test: Merge pipeline.py and run runner/tests plus tests/test_evaluation_identity.py and the canary. Grep for positional RunRecord( constructions. Compare overlay_diff output against the worker mock overlay for a task and confirm both score identically.
5. **Schema/migration extension by the merged subsystem reopens the non-concurrent migrate window and hits fail-closed validation**  
   why: migrate() is check-then-ALTER without a lock (db.py:417-435) and afa_app.py starts worker and API against the same freshly seeded DB. New columns on runs or evaluation_* must be added to db.migrate and _require_columns, not just SQLITE_SCHEMA, or SqliteRunStore(path) leaves old DBs without them (save_run(job_id=) fails). Missing or extra required columns cause RuntimeError and migrate_error, so ALL projections and control routes return 503 with no auto-clear until restart. An existing reports/app.sqlite is never re-seeded, so it silently diverges from any changed evidence.  
   how to test: Run 4 concurrent db.migrate() calls on a fresh seeded copy of the merged tree and count 'duplicate column name' errors. Start the merged tree against an old app.sqlite and against a fresh one. Delete reports/app.sqlite between runs to check reseeding.
6. **Two independent version sources and no run-vs-trial consistency check**  
   why: runs.task_version, evaluation_trials.task_version and snapshot_json can diverge silently: reuse, trial_detail and reports trust the trial/snapshot copy; aggregates trust runs.task_version; read-path 'current version' comes from manifest-then-task.json with a silent '1.0.0' fallback while write path is strict task.json. An integrity subsystem that rewrites or invalidates runs.task_version, adds run_scores rows with a new formula_version, or introduces a new evidence_state (unvalidated free text, no CHECK) will not be honored, and a new state is counted as completed but unclassified.  
   how to test: Post-merge, mutate runs.task_version and add a run_scores row (formula_version='v9') for a reused run, then compare /runs/{id}, /jobs/{id}/report.json, reuse creation and aggregates. Insert an unknown evidence_state and check report counters and limitations.
7. **Evidence-state and 'comparable' vocabulary collision**  
   why: ATLAS's evidence_state='unverifiable' is tied to resume unblocking (jobs.py:863-869), and 'provisional' means reused for trials but n<5 in the kernel. 'comparable' means only fresh with complete artifacts and ignores version currency. ORACLE's own integrity/valid/invalid verdicts have no hook in ATLAS and would be reported as 'comparable' regardless.  
   how to test: Inspect the merged code for any reuse of the strings unverifiable/provisional/comparable with different meaning. Run a fresh evaluation on a task ORACLE marks invalid and check report.json comparability.

### Claims the critic independently confirmed against the code

- Fencing atomicity: save_run(commit=False) issues an explicit BEGIN then SAVEPOINT (runner/afa_runner/store.py ~l.160-175); complete_trial's UPDATE is guarded by trial_state='claimed' AND claim_token AND EXISTS(job running AND owner_token) (afa_api/jobs.py:507-528) and raises TrialClaimError on rowcount!=1; worker rolls back and releases the claim (worker.py:359-381). The fence is evaluated after the first raw INSERT holds the write lock, so it is atomic. mark_terminal(owner_token) and touch_owner are also fenced (jobs.py:721-729, 926-933).
- append_event is NOT fenced (no owner predicate; MAX(seq)+1 read-then-insert, autocommit) at jobs.py:974-993, and run_diff/run_graded/run_scored events are committed before the evidence transaction (worker.py:324-358). Confirmed.
- Reuse compatibility predicate is exact equality of _snapshot_identity {model, backend, generation, tasks (ordered), repeats} between the source's STORED snapshot and a snapshot recomputed from current disk (jobs.py:288-295, 323). Source job status and runs.task_version are never checked (jobs.py:357-375; trial_detail selects run_task_version at :604 and never uses it).
- Drift checks: validate_snapshot_tasks runs at resume before any mutation (jobs.py:844, UPDATE at :851); _load_snapshot_task runs only for non-completed trials inside the loop (worker.py:270-306, 129-142) and compares task.version and directory sha256. Nothing is checked at claim or during a trial. _task_digest hashes every file via rglob with no exclusions (jobs.py:185-194).
- Historical DB protection: resolve_db_path never defaults to runs.sqlite (db.py:39-50); assert_writable_runtime_path catches path and samefile aliases (db.py:53-73). main.py:46 calls ensure_working_db OUTSIDE the try (52-60), so an evidence-bound app fails to start rather than degrading; the main.py:48-50 comment is misleading. Dockerfiles bake AFA_DB_PATH=/app/reports/runs.sqlite (api.Dockerfile:33, worker.Dockerfile:28) and only compose overrides it. ensure_working_db returns silently if evidence is absent or target exists, so a stale working DB is never refreshed (db.py:209).
- Evidence DB facts verified on a copy: sha256 42b6dad8...838ced, 720 runs (6 agents x 120), versions 1.0.0=120/4 tasks, 1.0.1=510/17, 1.0.2=90/3, 0 mixed (agent,task) cells, all 24 on-disk task.json versions equal the DB versions, runs.job_id already present, evaluation_jobs exists but is empty and lacks mode, source_evaluation_id, snapshot_json, owner_token and owner_started_at, so every seeded copy takes the ALTER path. tasks/manifest.json has no 'version' key.
- Migration is check-then-ALTER via _column_exists with no lock or BEGIN IMMEDIATE (db.py:417-435), so it is not concurrency-safe. afa_app.py launches the worker (start_worker, env AFA_DB_PATH) before uvicorn, and both run migrate() on the seeded DB (afa_app.py:113-126; worker.py:474-479), so the overlap is real. create_job and dispatch_job also call migrate().
- Ambiguous lookup: build_run returns ambiguous:true with candidate_run_ids when >1 rows (serialize.py:302-312), mapped to HTTP 409 (routes_readonly.py:98-106). It goes through _project/open_projection, so a mixed-version cell yields 503 first (store_load.py:168-178, projection.py:51-54). /runs/{id} bypasses projection (routes_readonly.py:109-119). Its INNER JOINs on run_scores/diffs mean partial runs read as 404.
- Mixed-version guard is per (agent, task) only (store_load.py:135-178); cross-agent version differences are pooled silently. The same guard is duplicated in examples/report_combined.py:159-169. Synthetic oracle/noop rows are stamped with the CURRENT version in the in-memory 'full' store only.
- openai_compat routing: master's factory_for sent both 'ollama' and 'openai_compat' to ollama_agent_factory (git show fd423ab:afa_api/worker.py:105-109). ATLAS worker.py:56-91 routes openai_compat to OpenAICompatAgent, which POSTs {base_url}/v1/chat/completions with no Authorization header (agents_openai.py:33-47). agents_openai.py is unchanged vs master; agents_ollama.py gains only set_run_seed. HTTPError is a URLError subclass and _INFRA_ERRORS includes URLError (agents_ollama.py:33-39), so every HTTP 4xx/5xx is voided INFRA_FAILURE. pipeline.py:108-121 checks timeout before infra.
- Params vs snapshot: worker executes from job.params (worker.py:236, 315-317). _job_params_from_row silently returns JobParams() (mock, model 'mock') on invalid or corrupt params_json (jobs.py:112-138); nothing cross-checks the snapshot. RunRecord.run_id was inserted before grade_report (pipeline.py:45), so it is a positional-binding hazard.
- Other confirmed items: _completed_indices is dead code (worker.py:105 only). A cancel request during the last trial yields 'canceled' even when all trials completed (worker.py:391-394). resume_job calls reclaim without recover_unlocked (jobs.py:848), so it is refused while the lease is fresh, whereas startup and serve use recover_unlocked=True (main.py:56, worker.py:480). A drift-blocked task iterates a stale trial_rows list, so the check and events repeat (worker.py:270-306). Settings ollama_base_url/openai_base_url/default_backend are never read outside schemas.
- Task-dir visibility: only jobs._task_digest globs the task directory (jobs.py:188). load_task, the grader (grader.py:309, 393 copies snapshot_dir only), the worker's reference overlay (worker.py:41-53 reads reference_dir only) and pipeline copytree (snapshot_dir) never read other files in tasks/<id>/. An added integrity/ dir is therefore invisible to execution and grading and affects only the digest.
- Canary: hard-coded sha literal 42b6dad8... is asserted at tests/test_phase0_acceptance_canary.py:602, after all behavioural assertions. The app is bound to a tmp copy, so the check only protects code that writes to the evidence path.
