# Phase 0 — closeout receipt

> **Phase 0 is closed.** The benchmark runtime (`phase0-integrity-v1`), the evidence-integrity system, the first
> modern local benchmark release (`phase0-modern-local-v1`: 5 models × 24 tasks × 5 repetitions = 600 accepted real
> runs), the data-driven Benchmark Releases UI and the live UI's connection to the evaluation-scoped API (§H) are
> frozen, verified and present on `master`. This receipt is the final Phase-0 engineering record. It records only
> what was checked on 2026-09-28; nothing here re-runs, re-scores or re-ranks a model.

## A. Phase-0 runtime

| | |
|---|---|
| Tag | **`phase0-integrity-v1`** (annotated, tag object `fb1f9779f89dff3f599fdf642b0599f078ddaf5a`) → **`7369e67e1ceb4b2a566986f247961f8a63f99567`** |
| Runtime paths pinned by it | `afa_api/` `8bed62d…`, `runner/` `22d57c0…`, `kernel/` `b6c72c6…`, `tasks/` `c3604fa…` (git tree ids) |
| Status on final `master` | all four trees **byte-identical** to the tag (so are `integrity/`, `db/`, `examples/`, `afa_app.py`) |

What that tag completes (each accepted and recorded earlier; not re-derived here):

- **ORACLE benchmark integrity — complete.** Task-pack audit engine, remediation and FULL audit
  (15 HEALTHY / 2 NEEDS_REVIEW / 7 PROVISIONAL / 0 INVALID) — `docs/BENCHMARK_INTEGRITY.md`, `docs/agents/ORACLE.md`.
- **ATLAS evaluation integrity — complete.** Fresh, traceable, durable evaluations under a recorded identity —
  `docs/integration/ATLAS_PRE_INTEGRATION_BASELINE.md`.
- **Integration — complete.** ORACLE × ATLAS merged, 2 integration defects fixed —
  `docs/integration/PHASE0_INTEGRATION_REPORT.md`.
- **Release hardening — complete.** Version-aware projections, fail-closed parameters, run provenance, migration
  safety; promoted to `master` by fast-forward — `docs/release/PHASE0_RELEASE_HARDENING.md`,
  `docs/release/PHASE0_MASTER_PROMOTION.md`.

## B. Official benchmark — Modern Local Benchmark v1

| | |
|---|---|
| Tag | **`phase0-modern-local-v1`** (annotated, tag object `29f94e0a2ebb13036994bdc3e7530836e4d1eac8`) → **`92a3b0c6195d7bc9c5856ad0788e8cfd1fdaf230`** |
| Scope | **5 models × 24 tasks × 5 repetitions = 600 fresh real runs** in 120 campaign-owned evaluations |
| Environment | local Ollama 0.31.1, one model at a time; Apple M4 Max, 36 GiB (operator-recorded); temperature 0.8, seeds 42–46, 180 s request timeout; no hosted or paid API |
| Plan | `campaigns/phase0-modern-local-v1/manifest.json`, canonical sha256 `a89bf89f41c54ddb219237882af595a2bfd7109c5733bf59dbae78671b4db6d1` |
| Promotion record | `docs/release/PHASE0_MODERN_LOCAL_PROMOTION.md`; campaign report `docs/campaigns/PHASE0_MODERN_LOCAL_CAMPAIGN.md` |

Official ranking (the kernel's ranking by Wilson 95 % lower bound; values read from the frozen
`results/outputs/modern-local-leaderboard.json`, unchanged):

| rank | model | passes | pass rate | Wilson 95 % | timeouts (full 180 s request) |
|---|---|---|---|---|---|
| 1 | `gpt-oss:20b` — gpt-oss 20B | 96 / 120 | 0.800 | [0.720, 0.862] | 0 (0) |
| 2 | `devstral-small-2:24b` — Devstral Small 2 24B | 71 / 120 | 0.592 | [0.502, 0.675] | 5 (0) |
| 3 | `qwen3.5:9b` — Qwen 3.5 9B | 40 / 120 | 0.333 | [0.255, 0.422] | 30 (19) |
| 4 | `qwen3-coder:30b` — Qwen3-Coder 30B-A3B | 18 / 120 | 0.150 | [0.097, 0.225] | 0 (0) |
| 5 | `qwen3.6:27b` — Qwen3.6 27B | 11 / 120 | 0.092 | [0.052, 0.157] | 105 (83) |

All five: 24/24 task coverage, 120 runs, 0 voided, 0 agent errors, rank band = rank (not provisional).

The tag freezes the benchmark **result** before any presentation code and was **not moved** by this closeout.

## C. Benchmark UI

| | |
|---|---|
| Feature source | `feature/benchmark-releases-ui` @ **`3bf3ad18f5157a1f8463f533330495d085b395eb`** — one commit on top of `92a3b0c` |
| Merge strategy | **fast-forward** (`git merge --ff-only`); the reviewed feature commit is kept as-is — no squash, no merge commit |
| `master` after the UI merge | **`3bf3ad18f5157a1f8463f533330495d085b395eb`** (tree `1d56f56bc6fedb698c8a69245a1362a2ac366349`, identical to the feature commit's) |
| `master` after this receipt | one further commit that adds only this file (parent `3bf3ad1`) |
| Design record | `docs/benchmarks/BENCHMARK_RELEASES_UI.md` |

- **Routes:** `/benchmarks` (default = newest OFFICIAL release), `/benchmarks/:releaseId`,
  `/benchmarks/:releaseId/models/:modelId`, `/benchmarks/:releaseId/methodology`. Pages are lazy-loaded, so the
  release data ships in its own chunks and the existing pages do not carry it.
- **Data generator:** `campaigns/afa_campaign/release_data.py`, run as
  `PYTHONPATH=campaigns python3 -m afa_campaign release-data [--check]`. It reads frozen evidence and writes only
  `web/src/data/benchmark-releases/<id>.json`; the output is deterministic and lists every source with its sha256.
- **Release definitions:** `campaigns/releases/phase0-modern-local-v1.json`, `campaigns/releases/historical-pre-phase0.json`
  (editorial facts the artifacts do not carry, each with a `source`).
- **Release registry:** `web/src/data/benchmark-releases/index.ts`, validated at load by `asBenchmarkRelease`
  (`web/src/lib/benchmarkReleases.ts`).
- **Modern Local release** (`phase0-modern-local-v1`): status `OFFICIAL`, ranked, 5 models, 120 evaluations,
  600 runs, 120 runs per model; model order, passes, Wilson bounds, timeouts and full-request timeouts equal the frozen
  leaderboard for all five models (checked field by field).
- **Historical release** (`historical-pre-phase0`): status `HISTORICAL`, `ranked = false`, `comparable = false`,
  6 models, 720 runs, recorded counts only. It carries no Wilson intervals, pass-rate ranks, model digests (only the
  two short prefixes the README documents, labelled as such), backend provenance, task digests or hardware
  (`environment = null`, `integrity = null`), and lists those under `not_recorded`. The non-comparability warning is an
  explicit release-level caveat.

## D. Evidence guarantees (demonstrated in this closeout)

| Guarantee | How it was checked |
|---|---|
| **600 / 600 accepted** | completeness receipt: `complete: true`, `problems: []`, 120 cells `succeeded`, 5 runs and 5 valid per cell; per model 24 cells / 120 runs |
| **0 missing, 0 extra** | `missing.cells = []`, `missing.positions = 0`; no untracked or disowned evaluations, 0 positions beyond plan, 0 superseded, 0 voided |
| **0 synthetic, 0 provenance conflicts** | `evidence_classes = {"real": 600}` in the completeness receipt and every model receipt (the validator raises a problem for any `synthetic`, `conflict` or `legacy` run) |
| **Task pins verified** | `launcher.check_task_pins` recomputed all 24 task versions and content digests from `tasks/` on `master`: 0 differences; manifest canonical sha256 recomputed: `a89bf89f…71b4db6d1` |
| **Model digests verified** | the manifest's 5 pinned digests equal the receipt's reference digests; 120 / 120 cells accepted at their pinned digest |
| **Result artifacts frozen** | all 20 `committed` entries of `campaigns/phase0-modern-local-v1/results/SHA256SUMS` verify; no file under `results/` is missing from it; `git diff phase0-modern-local-v1 master -- campaigns/phase0-modern-local-v1/` is empty |
| **Runtime frozen** | `afa_api/`, `runner/`, `kernel/`, `tasks/` tree ids on `master` = `phase0-integrity-v1` |
| **Historical DB unchanged** | `reports/runs.sqlite` sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` before, during and after every step |

## E. Important caveats (carried unchanged into the UI)

- **Qwen3-Coder 30B-A3B — protocol sensitivity.** 96 of 120 runs produced no applied edit (a documented count from the
  campaign database). In a diagnosed reproduction the model wrote a correct change but omitted AgentForge v1's required
  opening code fence; no raw responses were kept, so that cause is not established for all 96. The result reflects both
  coding performance and compliance with AgentForge v1's output contract — **not** a general statement about the
  model's coding capability.
- **Qwen3.6 27B — local latency constraint.** 105 of 120 runs were timeout-classified, 83 of them full 180-second
  request timeouts. This is performance under the fixed local latency budget on this hardware, not a general
  capability conclusion.
- **Historical results are not directly comparable.** 18 of the 24 task definitions changed and the 720 pre-Phase-0
  runs predate the evaluation-integrity system; the two result sets are never pooled.
- **Hidden-test isolation is UNVERIFIABLE** for all 24 tasks under the trusted-local sandbox; AgentForge makes no
  hidden-test isolation claim (shown under *Not claimed* on the benchmark integrity panel).

## F. Verification summary

Pre-merge checks ran on a detached checkout of `3bf3ad1`; the post-merge compact set ran on `master` = `3bf3ad1`.
None of them changed a tracked file.

| Check | Pre-merge | Post-merge |
|---|---|---|
| `PYTHONPATH=campaigns python3 -m afa_campaign release-data --check` | exit 0 — both datasets "match their sources" | exit 0 — same |
| `python3 -m pytest -p no:cacheprovider campaigns/tests/test_release_data.py` | **27 passed** | **27 passed** |
| `npm run typecheck` | pass | pass |
| `npm run build` | pass — 1924 modules; entry `index-CqYM_9WG.js` 359.31 kB (gzip 102.46 kB); benchmark chunks `BenchmarkRelease` 18.61 kB, `BenchmarkMethodology` 11.95 kB, `TaskMatrix` 10.64 kB, `BenchmarkModel` 10.12 kB | pass — same modules |
| `npm run test:focused` | **37 passed**, 0 failed, 0 skipped | — |
| `npm run test:benchmarks` | **34 passed**, 0 failed, 0 skipped (2.6 min) | — |
| `npm run test:real` (built app on a temp copy of the runtime) | **26 passed**, 0 failed, **1 skipped** (1.8 min) | — |
| Campaign tooling regression (`campaigns/tests`, whole directory) | **442 passed**, 0 failed, 2 skipped (241 s) | — |
| `reports/runs.sqlite` sha256 | `42b6dad8…838ced` | `42b6dad8…838ced` |

- `test:benchmarks` covers `/benchmarks`, the modern and historical releases, all 5 modern and 6 historical model
  pages, methodology, the release selector and back/forward, the task matrix (keyboard, one tab stop, 375 px), domain
  comparison, the integrity panel (no isolation claim), every caveat, not-found and malformed-URL states, and axe
  (serious/critical = 0) with no overflow at 375 / 768 / 1440 px.
- `test:real` covers every benchmark page plus the existing Overview, Leaderboard, Jobs, Tasks, Task, Agents and Agent
  views on the built app, the release data staying out of the entry chunk and the existing Leaderboard's styles. The
  skipped test is the optional single local Ollama smoke, which skips by design when Ollama is not reachable.
- The 2 skipped campaign tests assert case-insensitive-volume behaviour and skip on a case-sensitive volume.
- Verification environment: Linux container, Python 3.11.15, Node 22.22.2, npm 10.9.7, Playwright 1.63.0. The
  Playwright configs request `channel: "chrome"`; Google Chrome is not installed there, so the container's
  `/opt/google/chrome/chrome` was pointed at the pre-installed Chromium 141.0.7390.37. The API's Python dependencies
  (`fastapi`, `uvicorn[standard]`, `httpx`, `pydantic`, as listed in `docker/api.Dockerfile`) and `pytest` were
  installed for the run. No repository file was changed for either.

## G. Final repository state

| Ref | Value |
|---|---|
| `master` = `origin/master` after the UI merge push (`92a3b0c..3bf3ad1`, no force) | `3bf3ad18f5157a1f8463f533330495d085b395eb` |
| `master` = `origin/master` after the first receipt | `8692555eb2eb211489b5d870560a64ed545b57d5` (adds this file, parent `3bf3ad1`) |
| `master` = `origin/master` after the live-UI merge (§H, `8692555..310ff79`, no force) | `310ff792ff78f7c07551610d6269f92aed462df8` |
| `master` = `origin/master` at Phase-0 close | the commit that adds §H to this file, parent `310ff79` (documentation only) |
| `phase0-integrity-v1` | → `7369e67e1ceb4b2a566986f247961f8a63f99567` (unchanged) |
| `phase0-modern-local-v1` | → `92a3b0c6195d7bc9c5856ad0788e8cfd1fdaf230` (unchanged) |

**Final diff review, `phase0-modern-local-v1` → `master`:** 35 files from the UI commit (+13,541 / −5) plus this receipt:
the release-data generator and its CLI entry (`campaigns/afa_campaign/`), release definitions (`campaigns/releases/`),
its tests (`campaigns/tests/test_release_data.py`), the generated web datasets and registry, benchmark pages,
components, display helpers and styles (`web/src/`), benchmark and real-app browser tests and Playwright configs
(`web/tests/`, `web/playwright.*.config.ts`, `web/package.json` scripts), and documentation (`docs/`). Changes to
existing web files are additive: the Benchmarks nav link, safe breadcrumb decoding, an optional heading `id`, and a
benchmark route case. **No benchmark-result mutation** (`campaigns/phase0-modern-local-v1/` untouched) and **no
runtime-semantic mutation** (`afa_api/`, `runner/`, `kernel/`, `tasks/`, `integrity/`, `db/`, `examples/`,
`afa_app.py` untouched).

The §H merge adds 22 web and documentation files on top of that; it too leaves `campaigns/phase0-modern-local-v1/`
and every runtime path untouched.

**Tags.** No new tag was created. `phase0-integrity-v1` identifies the runtime and `phase0-modern-local-v1` the
benchmark result; the closeout's code state is identified by the `master` commit recorded above.

## H. Live UI — evaluation-scoped results and provisional domains (final Phase-0 change)

| | |
|---|---|
| Source | `claude/practical-keller-aej06v` @ **`310ff792ff78f7c07551610d6269f92aed462df8`** — one commit on top of `8692555` |
| Merge strategy | **fast-forward** (`git merge --ff-only`); the commit is kept as-is |
| Scope | `web/` (API client and types, results, monitor and run pages, domain matrix and agent profile, styles, tests) and two design docs; no Python, runtime, campaign, evidence or release-dataset change |

What it changes, using only API routes that already existed:

- **Evaluation-scoped results.** `/jobs/:id/results` reads `GET /jobs/{id}/report.json` — the report's counters,
  a grid and trial table from the persisted `evaluation_trials` rows with exact run ids, persisted provenance, task
  snapshots and the server's limitations, and `report.json` / `report.md` downloads. Global cells stay separate.
- **Exact run links.** `/jobs/:id/runs/:task/:idx` resolves through `GET /jobs/{id}/trials/{task}/{idx}` to the
  trial's `run_id`. The previous `(model, task, idx)` lookup answered `409` ambiguous once a model had two
  evaluations (reproduced on the real API before the change).
- **Monitor.** Ended evaluations overlay `GET /jobs/{id}/results` on the event tape; failed or canceled evaluations
  with unfinished trials offer Resume (`POST /jobs/{id}/resume`, same ID, completed trials kept). The event tape
  treats `job_resumed` as a restart, and SSE no longer closes on a replayed, already-seen terminal event.
- **Provisional domains.** A domain the kernel marks not displayable but with current evidence (`n_runs > 0`) shows
  its value, Wilson interval and a provisional label; a domain with no runs shows no value, never 0%. The server's
  `displayable` flag stays the only authority on the 5-task / 25-run threshold; nothing enters an overall score.
- **Unchanged by design.** Evaluations with unverifiable parameters stay fail-closed; the frozen benchmark-release
  pages are untouched (every Modern Local v1 domain is displayable).

Verification:

| Check | Before merge (session branch `310ff79`) | After merge (`master` = `310ff79`, compact) |
|---|---|---|
| `npm run typecheck` / `npm run build` | pass / pass | pass / pass (1925 modules) |
| `npm run test:focused` | **45 passed** | **45 passed** |
| Mocked browser specs (`version-evidence`, `routes`, logic specs) | **74 passed**; the 4 new browser tests also run against the previous build and fail there | — |
| `npm run test:async` | **10 passed** | — |
| `npm run test:benchmarks` | **34 passed** | — |
| `npm run test:real` | **27 passed**, 1 skipped (optional Ollama smoke), incl. a real cancel → resume and exact run links across two evaluations of one model | — |
| `release-data --check` / dataset pytest | exit 0 / **27 passed** | — |
| Frozen results (`git diff phase0-modern-local-v1 master -- campaigns/phase0-modern-local-v1/`) | empty | empty |
| Runtime trees `afa_api/`, `runner/`, `kernel/`, `tasks/` | = `phase0-integrity-v1` | = `phase0-integrity-v1` |
| `reports/runs.sqlite` sha256 | `42b6dad8…838ced` | `42b6dad8…838ced` |

## Scope boundary

This closeout merged and verified; it did not start Agent Protocol v2, a hosted benchmark, Phase 1, new tasks, new
model runs, a new scoring system or a new ranking method. A future factual correction to the release follows the
freeze policy in `docs/release/PHASE0_MODERN_LOCAL_PROMOTION.md` §4 — a new versioned correction and a new tag, never
an in-place rewrite.
