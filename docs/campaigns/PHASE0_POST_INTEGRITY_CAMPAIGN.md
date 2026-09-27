# Post-Phase-0 trusted baseline campaign — runbook

> **Status: CANCELLED (2026-09-28).** The project owner cancelled this six-model historical replication campaign
> before it was launched; it was never run and its frozen plan is kept unchanged for the record. It is superseded by
> the AgentForge Modern Local Benchmark, [`phase0-modern-local-v1`](PHASE0_MODERN_LOCAL_CAMPAIGN.md). The tooling
> described here is shared by both campaigns.

Campaign id: **`phase0-post-integrity-v1`** · Plan: [`campaigns/phase0-post-integrity/manifest.json`](../../campaigns/phase0-post-integrity/manifest.json)
· Tooling: `campaigns/afa_campaign` (`python3 -m afa_campaign <command>`). **Every terminal** that runs it must
first `cd <repo> && export PYTHONPATH=campaigns`; every command below assumes that.

## 1. Purpose

Produce a **fresh post-Phase-0 trusted baseline**: every one of the 6 roster models × 24 tasks × 5 repetitions
(**720 runs**) executed on the promoted Phase-0 release, at the current task versions, through the full ATLAS
evaluation lifecycle, on a real local model backend.

The 720 runs in `reports/runs.sqlite` remain the **pre-Phase-0 baseline**. They are never used as substitutes,
never pooled with the new cohort, never rewritten. 18 of the 24 tasks were strengthened by ORACLE after those runs
(new task versions), so for those tasks the old numbers describe a *different benchmark*.

## 2. The frozen plan

| Item | Value | Where it is pinned |
|---|---|---|
| Runtime release | tag **`phase0-integrity-v1`** = `7369e67e1ceb4b2a566986f247961f8a63f99567` (promoted to `master`) | `manifest.code`; the launcher refuses to run if `afa_api/`, `runner/`, `kernel/`, `tasks/` differ from the tag or have local changes |
| Backend | `ollama` at `http://127.0.0.1:11434` (real only; `mock` is refused by the manifest validator) | `manifest.backend` |
| Mode | `fresh` for every evaluation (no reuse; resume only for this campaign's own evaluations) | `manifest.mode` |
| Models (roster, fixed order) | `qwen2.5-coder:7b`, `qwen2.5-coder:3b`, `deepseek-coder:6.7b`, `llama3.2:latest`, `gemma2:2b`, `qwen3.5:9b` | `manifest.models` |
| Tasks | all 24, each pinned to its current **version and content digest** (computed with the runtime's own `task_snapshot`) | `manifest.tasks` |
| Repetitions | 5 per (model, task) cell | `manifest.repetitions` |
| Temperature | **0.8** | `manifest.generation` |
| Seed policy | **base seed 42; position `idx` (0–4) runs with seed `42 + idx`**, the ATLAS worker's per-trial seed (`set_run_seed`), identical for every model and task; a resumed position reuses its seed | `manifest.generation` |
| Model request timeout | 180 s (the task wall-clock limits of 20/60/120 s classify a trial when it ends, see §9) | `manifest.generation` |
| Granularity | **one evaluation per (model, task) cell**: `tasks=[task]`, `repeats=5`, name `campaign:phase0-post-integrity-v1:<phase>:<model>|<task>` | `manifest.evaluation_granularity` |
| Evidence scope | `real`, **and campaign-owned** (ledger) | `manifest.evidence_scope`, §8 |
| Campaign DB | `reports/phase0-campaign.sqlite`, **clean** (starts with zero runs) | `manifest.runtime` |
| Ledger / outputs | `reports/phase0-campaign/ledger.json`, `reports/phase0-campaign/outputs/` | `manifest.runtime` |
| Expected | 144 cells, 720 runs, 120 per model, 5 per cell; Phase A 51 cells / 255 runs; Phase B 93 cells / 465 runs | `manifest.expected` |

The manifest was built by `afa_campaign build-manifest`, which **refuses** to produce a plan if the task pack, the
historical evidence DB and ORACLE's `integrity/pack-audit/remediation-manifest.json` disagree about any version or
any prior-pass count. Once a campaign has launched, its ledger records the manifest's sha256; `launch`, `resume`,
`supersede`, `disown`, `phase-a-report` and `compare-baselines` refuse a manifest whose hash differs from the
ledger's (`refused:`, exit 3); `preflight` and `validate` fail with the mismatch as a problem (exit 1);
`baseline-report` exits 1 with only its generic "not complete" message (and is `refused:`, exit 3, with
`--allow-incomplete`); and `status` reports it: **the plan is frozen**.

**Why these generation settings.** The pre-Phase-0 runs were not uniform. The README documents the *P0 completion
runs* at temperature 0.8, base seed 42, Ollama 0.17.4 (it does not enumerate which models' runs those were; 0.8 / 42
are also the values `examples/eval_persist.py` hard-codes). `qwen3.5:9b` was evaluated separately by a local app job
(`eb54c065…`, runs 1101–1220) at temperature 0.6, base seed 42, 180 s request timeout
(`reports/qwen3.5-9b-evaluation-2026-09-17.md`). The new cohort uses **one setting for all six models**; 0.8 / 42
matches the documented P0 settings, which makes the six same-version tasks the most comparable for those models.
The per-run seeds are *not* comparable with history (P0: one counter per model across the whole pack; qwen3.5:9b:
not documented). All of this is recorded in `manifest.historical_evidence.documented_generation` and disclosed by
the comparison reports. To change any setting, rebuild the manifest **before** the first launch; afterwards it is
frozen.

## 3. Before you launch (all must hold)

1. **All six roster models are installed.** As prepared (2026-09-26, Ollama 0.31.1) only `qwen3.5:9b` is present
   (digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`); the other five are **missing**
   ([`model-inventory-2026-09-26.json`](../../campaigns/phase0-post-integrity/model-inventory-2026-09-26.json)).
   Pull exactly these names (never a substitute tag):
   ```bash
   ollama pull qwen2.5-coder:7b && ollama pull qwen2.5-coder:3b && ollama pull deepseek-coder:6.7b \
     && ollama pull llama3.2:latest && ollama pull gemma2:2b
   ```
   Then record the inventory:
   ```bash
   PYTHONPATH=campaigns python3 -m afa_campaign inventory --out reports/phase0-campaign/inventory-prelaunch.json   # exits 1 while any roster model is missing
   ```
   The README recorded short digests `dae161e27b0e` (`qwen2.5-coder:7b`) and `a80c4f17acd5` (`llama3.2:latest`) for
   the historical runs; a different digest today is not an error but must be disclosed in the comparison.
2. The checkout is `master` at or after the campaign-preparation commits (which contain this tooling) and its
   `afa_api/`, `runner/`, `kernel/`, `tasks/` equal tag `phase0-integrity-v1` with **no local changes** (the launcher
   checks this with git before every launch and resume; it picks a `git` that actually runs, falling back to
   `/usr/bin/git`, and `AFA_GIT` overrides the choice). `--no-code-check` and `--no-warmup` exist for rehearsals
   only: they are recorded, and a cell submitted without warm-up, or submitted, resumed or finalized without the
   code check, is never official evidence — the launcher rejects it when it finishes and halts.
3. Nothing else will use the model server for the whole campaign (no UI evaluations, no other Ollama clients).
4. The machine can stay awake. Runtime estimate from history: the 720 historical runs used about 2.6 h of model
   time in total (recorded run durations; median per run 2–6 s for the five smaller models, 25 s for
   `qwen3.5:9b`), and the `qwen3.5:9b` job (its 120 runs, ids 1101–1220, are part of those 720; 36 timeouts) took
   2 h 04 min end to end. A trial that **times out can cost up to the full 180 s request timeout** (see §9), so
   `qwen3.5:9b` dominates. Budget roughly **4–8 hours** for all 720 runs, including grading and warm-ups.
5. Start Ollama with a long keep-alive so models are not unloaded between trials, e.g.
   `OLLAMA_KEEP_ALIVE=60m ollama serve` (the launcher also loads the model before every cell).
6. **Freeze the Ollama server for the whole campaign.** The server version is part of the campaign's identity (it
   supplies every inference setting the campaign does not send: context length, sampler defaults, runner): the
   launcher records it at the first launch and halts, or rejects the cell, if it changes. Turn off Ollama's
   automatic updates (the macOS app updates itself and restarts), and keep the server's environment
   (`OLLAMA_CONTEXT_LENGTH`, `OLLAMA_KV_CACHE_TYPE`, `OLLAMA_FLASH_ATTENTION`, `OLLAMA_NUM_PARALLEL`, …) unchanged
   from the first launch to the last — those settings are invisible to the tooling.

## 4. Setup

```bash
cd <repo>                                     # the same checkout for the app, the worker and the launcher
export PYTHONPATH=campaigns
python3 -m afa_campaign init-db               # creates reports/phase0-campaign.sqlite (clean, zero runs)
OLLAMA_KEEP_ALIVE=60m ollama serve            # (if not already running) on 127.0.0.1:11434
AFA_DB_PATH="$PWD/reports/phase0-campaign.sqlite" AFA_NO_BROWSER=1 python3 afa_app.py   # API + worker (keep running)
python3 -m afa_campaign preflight             # (another terminal) must print "preflight OK"
```

`init-db` **must run before the app is first started**: the app seeds a *missing* database from the historical
evidence. If that happened, `preflight` refuses (the clean strategy forbids job-less rows): **stop `afa_app.py`**,
delete `reports/phase0-campaign.sqlite` **together with** `reports/phase0-campaign.sqlite-wal` and
`reports/phase0-campaign.sqlite-shm`, run `init-db` again, then restart the app.

**Start the app from this checkout (preflight needs it running), and do not switch branches or edit runtime paths
while it runs.** The launcher proves that *its* checkout's runtime paths equal the release tag and that every
evaluation snapshot pins the frozen task digests (the app computes those from its own `tasks/`), but it cannot see
which `afa_api/`, `runner/`, `kernel/` code a separately started app process has loaded.

**Topology rule.** Run the API and the worker on **one host with one `TMPDIR`**, the way `afa_app.py` does (the
evaluation owner lock lives in the temp directory). Do **not** use the split `docker-compose.yml` api/worker
containers for the campaign: the API's startup recovery cannot see the worker's lock there and can re-execute a
running evaluation.

## 5. Phase A — the 51 prior-pass cells (early warning)

Selection rule (reproducible from `integrity/pack-audit/remediation-manifest.json`): every (model, task) cell on
one of the **18 version-changed tasks** where the model passed at least once in its 5 historical runs. There are
**51 such cells** (qwen2.5-coder:7b 15, deepseek-coder:6.7b 11, qwen3.5:9b 10, llama3.2:latest 8, qwen2.5-coder:3b 5,
gemma2:2b 2), **255 runs**. They come first because a strengthened hidden-test oracle is most likely to change
exactly the scores that previously passed.

```bash
python3 -m afa_campaign plan --phase A
python3 -m afa_campaign launch --phase A --confirm phase0-post-integrity-v1
python3 -m afa_campaign status --phase A          # any time, from another terminal
python3 -m afa_campaign validate --phase A        # receipt: reports/phase0-campaign/outputs/completeness-receipt-A.json
python3 -m afa_campaign phase-a-report            # reports/phase0-campaign/outputs/phase-a-comparison.{json,md}
```

The launcher runs **one evaluation at a time**: it first finishes every campaign evaluation still in flight — of
any phase (after a resume or a killed launcher) — then refuses to submit while *anything* is queued or running
(asking both the API and the database), and waits for each evaluation to finish before creating the next.
Before **every** submission (and every resume) it re-checks the model's Ollama digest and the Ollama server version
against the campaign's first launch and loads the model (an empty-prompt generate), so a cold load is not charged
to a trial's wall-clock budget. While an evaluation runs it re-reads the digest and the server version every 30 s
and checks that no other evaluation is running; before accepting the cell it checks the identity once more (a
failed read is tried three times in all, 10 s apart) and that no other evaluation's trials overlapped this one's in
time — completed trials, and trials still in flight — and it applies the validator's own acceptance predicate
(§8), so it never marks a cell succeeded that `validate` would refuse. Any change or overlap **rejects** the cell
(its evidence is excluded) and halts; `validate`, `status` and the analysis re-check overlaps every time they run,
so an overlap that completes later still excludes the cell. Overlaps shorter than one second are invisible (the
runtime's timestamps have one-second resolution). Limits: a re-tag that is
undone within one 30 s poll interval can go unseen; nothing watches an evaluation while no launcher is waiting on
it (after a killed launcher, or between `resume` and the next `launch`) — it is then checked only at acceptance;
trials that ATLAS recovery re-runs after an app restart are not warmed by the launcher (see §7); and other clients
of the Ollama server outside AgentForge are invisible (§3 item 3).

**Review Phase A before Phase B.** The early-warning report compares each cell with its historical runs:
`stable` (95 % Wilson intervals overlap), `improved` / `regressed` (non-overlapping), or
`incomparable/insufficient`. These are **observed differences on a changed benchmark definition**: every Phase-A
task has a new version, so a lower fresh pass rate can simply mean the old hidden tests were too lenient. It is not,
by itself, evidence that a model got worse.

## 6. Phase B — the remaining 93 cells (465 runs)

Only after Phase A is reviewed and accepted:

```bash
python3 -m afa_campaign launch --phase B --confirm phase0-post-integrity-v1
python3 -m afa_campaign validate --phase all      # must report COMPLETE: 144 cells, 720 runs
```

## 7. Resume procedure

Everything is restartable; the **ledger is authoritative** for what belongs to the campaign.

* **Launcher interrupted** (Ctrl-C, crash, reboot): after a reboot, first restart Ollama and `afa_app.py` as in the
  next bullet (load the in-flight cell's model before starting the app); then run the same `launch` command again.
  Succeeded cells are skipped; an evaluation that is still queued/running, or that finished while no launcher was
  waiting (`status` shows it as `awaiting_finalize`), is finalized; an entry written just before a crash
  (`submitting`, no id) is reconciled by the evaluation's persisted name — adopted if exactly one exists, a
  **duplicates** halt if more than one, dropped (the cell starts over) if none exists.
* **App/worker interrupted mid-evaluation**: first load the cell's model (e.g.
  `curl -s http://127.0.0.1:11434/api/generate -d '{"model":"<model>","prompt":"","keep_alive":"60m"}'`), then
  restart `afa_app.py` with the same `AFA_DB_PATH`. ATLAS startup recovery requeues the interrupted evaluation
  **under the same id** and runs it at once; completed positions are kept, interrupted positions re-run with their
  original seeds. The launcher keeps waiting (it tolerates up to 30 min of API downtime).
* **An evaluation ended `failed` or `canceled`**: the launcher halts. After fixing the cause:
  `python3 -m afa_campaign resume --cell '<model>|<task>'` (same-id ATLAS resume; refused while any other campaign
  evaluation is in flight or anything is queued/running, and for an evaluation that recorded an identity or
  concurrency violation — supersede that one; it re-runs the code check, re-checks the task pins, the model digest
  and the server version, and loads the model first), then run `launch` (either phase) to wait for it and continue.
  The cell is marked in flight **before** the resume request, so if the command dies or loses the answer, `launch`
  reconciles it: it settles that resume once, from the app's own `job_resumed` events (an event logged from the
  request time on, within 5 minutes, means it was executed), then waits for the evaluation if the app resumed it,
  and halts on it again if not. A refused connection (the app is down) is definitive: nothing was resumed, the cell
  stays failed/canceled, and you simply run `resume` again once the app is up. Limit: a lost request that a
  *stalled* app executes only after that settlement cannot be told from a resume outside the tooling, so the cell is
  rejected (supersede it); restart a stalled app before running `launch` so it drops queued requests.
  `resume` also refuses — and advises `supersede` — a cell whose start was not code-checked or not warmed up
  (resuming it could never make it official).
* **Never resume a campaign evaluation any other way** (for example a direct `POST /api/v1/jobs/<id>/resume`; the
  web UI has no resume action, and its Retry creates a clone, see §8): such a resume bypasses the code, identity and
  busy checks and the warm-up. It is detected when the database shows the evaluation active or succeeded while the
  ledger says failed/canceled, when the evaluation no longer matches the snapshot taken when the campaign halted on
  it (finish time, completed positions, resume events), or when the app's `job_resumed` events outnumber the
  tooling's executed resumes. The next `launch` waits for it to finish and **rejects** the cell whatever its result;
  `resume` of that cell rejects it at once (`refused:`, exit 3) without waiting; `validate` refuses such a cell too.
  Supersede it for a fresh re-evaluation (the next `launch` still refuses to submit while that evaluation runs).
* Completion is **never** inferred from the presence of runs for a model and task — only from campaign-owned
  evaluations.

## 8. Evidence scope, ownership and duplicates

The official baseline uses **only campaign-owned evidence**: evaluations referenced by an *active* ledger entry,
each of which passes every cell check (below). This is stricter than `?evidence=real`: an unrelated real evaluation
in the same database — a UI experiment, a retry clone, a rehearsal — never counts. With the clean database the app's
default `benchmark` scope and `real` scope show the same rows, but **analysis never relies on that**.

A cell's evaluation counts only if: it succeeded; it is `fresh`; its persisted parameters verify against its own
snapshot and equal the manifest (model, single task, 5 repeats, backend kind and URL, temperature, seed, timeout,
name); its snapshot pins the frozen task version **and digest**; positions 0–4 are all completed with fresh evidence
from this evaluation; every raw run is owned by it, matches its position, has `runs.backend_kind = 'ollama'`,
classifies as `real` provenance, and has a score row (formula v0.1) and a diff row; and it owns no other run. In
addition its active ledger entry is `succeeded`; all 5 positions are **valid** (an infrastructure-voided position
makes the cell incomplete); its model digest and the Ollama server version at submission and at acceptance equal
the campaign's first-launch values, with no identity violation recorded while it ran; no other evaluation ran
alongside it; it was submitted, every resume was made, and it was accepted under a passing runtime-code check; the
model was loaded before its start and before every resume; and the app resumed it no more often than the tooling
did (its `job_resumed` events do not outnumber the ledger's executed resume records, all of them settled). This is
one predicate (`validate.assess_cell`), shared by the launcher's acceptance step, `validate`, `status`, `supersede`
and the analysis.

Duplicates: an evaluation carrying this campaign's name that the ledger neither owns (actively or as a superseded
entry) nor has disowned — including two such evaluations with one name — **halts** the launcher and fails
validation. (A superseded evaluation and its fresh replacement legitimately share one name.) Such evaluations are
never silently included. (A UI "Retry" of a campaign evaluation creates
exactly such a clone: do not use the UI's retry during the campaign.) After investigating, record each one with
`python3 -m afa_campaign disown --evaluation <id> --reason "<what it was>"` (it must be terminal: cancel it in the
UI/API first). A disowned evaluation stays in the database, never counts, and is listed in every receipt.

Model identity is tracked **outside** AgentForge's persisted provenance: each launch records Ollama's inventory
(server version; per model name, digest, size, modified time, details) in the ledger, and every ledger entry records
the model digest and server version at submission and at acceptance (plus any mismatch observed while it ran). The
first launch's digests and server version are the campaign's reference.

## 9. Failure procedure

| Event | What the tooling does | Operator action |
|---|---|---|
| Model fails a task (tests fail, wrong patch, `AGENT_ERROR`) | Normal AgentForge result, counted in *n* | none |
| Trial exceeds the task's wall-clock limit (`TIMEOUT`) | Counted in *n* as a failure (S = 0). The task limit (20/60/120 s) is applied when the trial ends: a trial runs until the model answers or the 180 s request timeout fires, and is scored `TIMEOUT` if it exceeded the limit — a slow model is always a `TIMEOUT`, never a void | none |
| Infrastructure failure (backend unreachable → `INFRA_FAILURE`, voided) | Excluded from *n*, never counted against the model; cell → `needs_attention`; **launcher halts** | fix the backend; then `supersede --cell … --reason …` → the next `launch` re-evaluates the whole cell fresh. A campaign cell needs all 5 positions valid; voids are never "accepted short" |
| Trials that ran the full 180 s request timeout | The runtime scores them `TIMEOUT` (its wall-clock check precedes infra failure, so a stalled server and a slow model look alike). Before accepting the cell the launcher asks the model for one token: failure → cell `needs_attention` (durable), **halt**; success → accepted as model behaviour, with a warning on the ledger entry. A stall that has already cleared by then is not detectable | if halted: fix the backend, then `supersede` (never just relaunch) |
| Evaluation `failed` / `canceled` | cell → `failed`/`canceled`; **halt** (→ `rejected` instead if it had recorded an identity or concurrency violation) | fix cause; `resume --cell …` (same id) or `supersede` |
| Corrupt / unverifiable evaluation (persisted parameters fail verification) | cell → `rejected`; **halt**; never resumed | **investigate**; then `supersede` with the finding as reason |
| Evidence fails a campaign check (backend provenance conflict, wrong version/digest, extra runs, non-real class) | cell → `rejected`; its evidence is **excluded**; **halt** | investigate; `supersede` |
| **Task version or digest changed** (checked before every submission and in every snapshot) | **STOP THE CAMPAIGN** | restore the frozen task files; a changed benchmark needs a new campaign/manifest — never continue half on one digest and half on another |
| A roster model's Ollama digest, or the Ollama server version, changed (at preflight, before every submission, every 30 s while running, before acceptance) | preflight or before a submission: **halt**, nothing submitted; around or during an evaluation: cell → `rejected` (durable), evidence excluded, **halt**; Ollama unreachable at acceptance (after 3 tries): cell → `needs_attention` (durable), **halt** | the model identity moved: restore the original weights / server version (then `supersede` any rejected cell for a fresh re-evaluation) or decide to restart the campaign. Restoring and relaunching never accepts a rejected cell. For `needs_attention` (Ollama unreachable at acceptance): fix Ollama, then `supersede` the cell (never just relaunch) |
| Unexpected duplicate / untracked campaign evaluation | **halt**; never counted | investigate (UI retry? second launcher? lost ledger?), then `disown --evaluation … --reason …` |
| Another evaluation queued/running on the app | preflight refuses a non-campaign one; campaign-named ones are reconciled or halt right after preflight; every submission and resume re-checks that nothing is queued or running (API and database) | wait for it / stop it |
| Another evaluation ran **alongside** a campaign evaluation (seen while waiting, or trials overlapping in time at acceptance) | cell → `rejected` (durable), evidence excluded, **halt** | stop the other evaluation's source; `supersede` the cell |
| A campaign evaluation was resumed outside the tooling (a direct API call) | detected even if that resume failed again: the next `launch` waits for it, then cell → `rejected` (durable), **halt**; `resume` of the cell → `rejected` at once (refused) | `supersede` the cell (the next `launch` still refuses to submit while that evaluation runs) |
| A cell that would not pass the validator (submitted with `--no-warmup`, or without the code check) | cell → `rejected` when it finishes — also when it fails, since resuming it could never make it official — **halt** | `supersede` the cell and launch without the rehearsal flag |
| A ledger evaluation is missing from the campaign database (DB replaced or restored) | in flight: cell → `rejected`, **halt**; failed/canceled: stays halted and `resume` is refused by the app (HTTP 404); succeeded: `status` shows `succeeded-but-invalid` and `validate` fails | investigate the database; `supersede` the cell |
| Historical evidence DB hash changed (a non-empty, uncheckpointed `reports/runs.sqlite-wal` counts as a change) | checked at preflight, before every submission, at the end of every launch, by `validate` and by the comparison reports: **halt** / refuse | investigate immediately (it is never a campaign write target) |

To supersede: `python3 -m afa_campaign supersede --cell '<model>|<task>' --reason "<what happened>"` (always quote
the cell key: it contains `|`); the next `launch` of that cell's phase re-evaluates it fresh under the same
evaluation name. `supersede` records the written reason, keeps the old evaluation in the database (reported in every
receipt), and is **refused for a succeeded cell the validator accepts**: replacing good evidence because of its
result would be cherry-picking. (A `succeeded` entry the validator refuses — `status` shows it as
`succeeded-but-invalid` — can be superseded; the refusal never depends on the result, and its problems are recorded
with the supersession.)
Superseding is for infrastructure, corruption and identity problems — never for results someone dislikes; reviewers
see every superseded evaluation and its reason in the receipt and the provenance summary.

## 10. Monitoring

`python3 -m afa_campaign status [--phase A|B|all] [--json]` — planned runs (720 for `all`), completed, remaining,
passed, failed (incl. timeouts), voided/infra, cells/models/tasks complete, cells incomplete, evaluations running,
halted/failed evaluations, superseded entries, and per-model progress. `completed`/`passed`/`failed` count only
evidence the validator accepts; positions of evaluations in flight or resumable (`failed`/`canceled`) are shown as
*in progress*, and evidence that can never count (`rejected`, `needs_attention`, or a `succeeded` cell the validator
refuses: `succeeded-but-invalid`) as *excluded*. A cell whose evaluation has finished but that no launcher has
accepted or rejected yet is listed as `HALTED: … is awaiting_finalize` — run `launch` (either phase) to finalize it.
Voided positions never appear under `voided/infra` (a cell with voids is `needs_attention`, never accepted): `status`
lists such a cell as `HALTED: … is needs_attention`, and the number of voided positions is in the launcher's HALT
message and in the cell's ledger entry (`warnings` and `summary.voided`); `validate` lists the cell as missing. It reads the ledger and the database read-only, works with the app stopped, and
says so when the campaign database is missing. The app UI also shows each evaluation live (Evaluations page).

## 11. Completeness validation

`python3 -m afa_campaign validate --phase all` exits `0` only when **every** planned cell is complete and valid. It asserts, from campaign-owned evaluations only: 6 models, 24 tasks per model, 5 **valid** runs
per cell (a voided position makes the cell incomplete), 120 per model, 720 total; `backend_kind = ollama`;
provenance class `real` (synthetic = 0, conflict = 0, legacy = 0); current task version and frozen digest for every
run; every cell's model digest and Ollama server version (at submission and at acceptance) equal to the campaign's
first-launch values; every cell accepted under the §8 predicate (ran alone, code-checked and warmed at every start);
no missing position, no extra position, no untracked campaign evaluation (disowned ones are listed, not counted); the
task pack still matches the frozen digests; the historical DB hash unchanged. Launches made with `--no-code-check` or
`--no-warmup` are listed as warnings (cells they submitted are never accepted; a `--no-code-check` launch also taints
every cell it finalized, and `resume --no-code-check` every cell it resumed).
It writes a machine-readable receipt (expected / present / missing / extra, per model, per cell, superseded
evaluations, and the voided positions of `succeeded` entries; a cell halted as `needs_attention` for voids is listed
as missing, and its voids are recorded in its ledger entry).

## 12. Analysis

| Output | Command | File (under `reports/phase0-campaign/outputs/`) |
|---|---|---|
| Completeness receipt | `validate --phase all` | `completeness-receipt-all.json` |
| Phase-A early warning (51 cells vs history) | `phase-a-report` | `phase-a-comparison.{json,md}` |
| Official post-Phase-0 baseline: leaderboard (Wilson-LCB ranks), 24×6 task matrix, per-model domain profiles, provenance summary | `baseline-report` (refuses until complete; `--allow-incomplete` gives a clearly-labelled PROVISIONAL report) | `post-phase0-baseline.{json,md}` (official) or `post-phase0-baseline-PROVISIONAL.{json,md}` |
| Pre- vs post-Phase-0 per cell | `compare-baselines` | `pre-vs-post-phase0-comparison.{json,md}` |

The official leaderboard is derived from **current task versions + fresh campaign-owned evidence + real backend
only**: no mock, no reused historical evidence, no old-version runs, no conflict provenance, no unrelated real runs.
Never use the app's own `/leaderboard` (or its UI) for official numbers: it ranks every real row in the database,
including evaluations the campaign does not own.
Model identity is reported twice and kept distinct: AgentForge's persisted provenance (`runs.backend_kind`,
evaluation snapshots) and the external Ollama inventory snapshot (names, digests, sizes) recorded at each launch.

## 13. Old vs new baseline

`compare-baselines` puts every cell side by side: old version, new version, whether they differ, old/new counts,
pass rates and scores. Where the task version changed (18 tasks) the cell is labelled **NOT DIRECTLY COMPARABLE**
— the benchmark changed. For the 6 same-version tasks (`escape-html`, `fix-binary-search`, `fix-roman-numerals`,
`implement-lru-cache`, `async-batched`, `two-sum-indices`) a direct comparison is more defensible, but the execution
stack still differs (evaluation path, seeds, temperature for `qwen3.5:9b`, Ollama version, possibly model digests)
and the report discloses each difference. The historical baseline is read-only and is never overwritten.

## 14. Freezing the final baseline

1. `validate --phase all` → exit 0 (every position valid, every identity check passed).
2. `baseline-report`, `compare-baselines`, `phase-a-report`.
3. Stop `afa_app.py`, checkpoint the WAL (`sqlite3 reports/phase0-campaign.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"`),
   confirm `reports/phase0-campaign.sqlite-wal` is empty or absent, then record the `sha256` of
   `reports/phase0-campaign.sqlite` and of the ledger in the receipt's commit message.
4. Copy the outputs, the receipt, `reports/phase0-campaign/ledger.json` and `reports/phase0-campaign/evaluation-reports/`
   (not the database) into `campaigns/phase0-post-integrity/results/`, commit, and tag the commit (suggested
   `post-phase0-baseline-v1`). Keep the campaign database itself **together with its ledger** as an archived
   artifact outside git (both are gitignored), or promote them to read-only evidence files in a separate, reviewed
   change.
5. From then on the campaign database is read-only evidence: never run another evaluation into it.

## 15. Rehearsal (dry run) on scratch data

A derived plan with identical pins exercises the exact launcher/app path without touching campaign state:

```bash
python3 -m afa_campaign derive --out <scratch>/dry.manifest.json --campaign-id phase0-post-integrity-dryrun \
  --models qwen3.5:9b --tasks sanitize-filename,fix-binary-search --repetitions 1 \
  --db <scratch>/dry.sqlite --runtime-dir <scratch>/dry --api-url http://127.0.0.1:8790
python3 -m afa_campaign --manifest <scratch>/dry.manifest.json init-db
AFA_DB_PATH=<scratch>/dry.sqlite AFA_PORT=8790 AFA_NO_BROWSER=1 python3 afa_app.py &
until curl -sf http://127.0.0.1:8790/api/v1/healthz >/dev/null; do sleep 1; done   # wait for the rehearsal app
python3 -m afa_campaign --manifest <scratch>/dry.manifest.json launch --phase A --confirm phase0-post-integrity-dryrun
python3 -m afa_campaign --manifest <scratch>/dry.manifest.json validate
kill %1                                       # stop the rehearsal app: it is another model-server client
```

Rehearsal runs are **never campaign evidence** (different campaign id, name prefix, database and ledger).

## 16. File map

| Path | Tracked | Content |
|---|---|---|
| `campaigns/afa_campaign/` | yes | tooling |
| `campaigns/phase0-post-integrity/manifest.json` | yes | the frozen plan |
| `campaigns/phase0-post-integrity/model-inventory-2026-09-26.json` | yes | preparation-time Ollama inventory (5 models missing) |
| `reports/phase0-campaign.sqlite` | **no** (gitignored) | campaign runtime DB |
| `reports/phase0-campaign/ledger.json` | **no** | campaign ledger (ownership) |
| `reports/phase0-campaign/evaluation-reports/` | **no** | per-evaluation report JSON saved by the launcher |
| `reports/phase0-campaign/outputs/` | **no** | receipts and analysis (copy to `campaigns/.../results/` when freezing) |
