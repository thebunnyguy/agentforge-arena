# Phase-0 master promotion — acceptance receipt

> **Real 720-run campaign has NOT started.** Neither Phase A (51 cells) nor Phase B has been launched. The only model
> executions performed during this mission were five scratch dry runs of the campaign tooling (§6: 16 persisted
> trials of `qwen3.5:9b`, plus the attempts interrupted by the crash tests), in scratch databases outside the
> repository; they are not campaign evidence.

## 1. What was promoted

| | |
|---|---|
| Release source | `release/phase0-current-benchmark` @ **`7369e67e1ceb4b2a566986f247961f8a63f99567`** (verified: `origin/release/phase0-current-benchmark` resolved to exactly this commit before anything changed) |
| `master` before | `fd423abfcc6bb883b513c2b967fb5a2683b8b710` (= `origin/master`; the known pre-Phase-0 baseline: the common base of ORACLE and ATLAS; no unexpected commits) |
| Strategy | **fast-forward** (`git merge --ff-only`): `fd423ab` is an ancestor of the release, so every ORACLE, ATLAS, integration and release-hardening commit is preserved as-is — 50 commits, 2 of them the ORACLE+ATLAS integration merges. No squash, no replay, no merge commit needed |
| `master` after promotion | **`7369e67e1ceb4b2a566986f247961f8a63f99567`** |
| Release tag | **`phase0-integrity-v1`** (annotated) → `7369e67e1ceb4b2a566986f247961f8a63f99567` — the runtime code that executes the first trusted post-Phase-0 campaign |
| Historical evidence | `reports/runs.sqlite` sha256 **`42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced`** — unchanged before, during and after every step below |

## 2. Master tree equivalence (proved, not assumed)

| Check | Result |
|---|---|
| `git rev-parse master` vs release | identical commit `7369e67…` |
| Tree object | `3dba05062fc464d6bf5d203ddd281e27f5996499` for both |
| `git diff 7369e67..master` | **empty** |
| `git ls-tree -r` (mode, blob sha, path) | identical, 766 files |
| Old master `fd423ab` | ancestor of the new master (nothing overwritten); `master` had **no** independent changes to enumerate |

**Master contains the complete accepted Phase-0 release.** The campaign-preparation commits that follow the tag
touch only `campaigns/`, `docs/`, `pyproject.toml` (test/import paths) — never `afa_api/`, `runner/`, `kernel/` or
`tasks/`; the campaign launcher enforces that those runtime paths equal the tag before it runs.

## 3. Pre-promotion verification (clean detached worktrees at `7369e67`)

| Check | Result |
|---|---|
| Full Python suite (`python3 -m pytest -p no:cacheprovider -ra`) | **1202 passed**, 0 failed, 0 skipped, 4 warnings, 684.8 s; 0 `*.pyc` under `tasks/`; no tracked change |
| Phase-0 acceptance canary | 1 passed |
| Cross-system ORACLE + ATLAS (`tests/test_integration_oracle_atlas.py`) | 58 passed |
| Release hardening (`tests/test_phase0_release_hardening.py`) | 235 passed |
| Campaign-readiness simulation | 1 passed |
| Migration concurrency | 44 passed |
| Red-team / hardening regressions | 53 + 67 + 81 + 64 + 44 = 309 passed |
| Web `npm run typecheck` / `npm run build` | pass / pass (assets `index-S4ge2yVQ.js`, `index-DhWUMSEj.css` — byte-identical names to the release build) |
| FULL ORACLE audit (`afa_integrity audit --all --full --workers 4`) | **15 HEALTHY / 2 NEEDS_REVIEW / 7 PROVISIONAL / 0 INVALID** |
| Audit vs the committed integrated baseline (`integrity/pack-audit/integrated-full-summary.json`), every field of all 24 task reports, 192 checks, 73 controls | **identical** except `provenance.platform` (`macOS-26.3` → `macOS-27.0`: the host OS was upgraded since the baseline) and timing fields |
| `reports/runs.sqlite` sha256 before / after (worktree and main checkout) | `42b6dad8…838ced` / `42b6dad8…838ced` |

Pass counts, durations, web asset names and the fresh audit's field-by-field comparison in §3 and §4 are recorded
from the verification session; those artefacts (JUnit files, build output, the fresh audit JSON) were produced in
scratch worktrees and are not committed. The test counts are reproducible by collection at the tag, and the audit
baseline they were compared with is committed (`integrity/pack-audit/integrated-full-summary.json`).

## 4. Post-promotion verification (clean worktree at `master` = `7369e67`)

| Check | Result |
|---|---|
| Full Python suite | **1202 passed**, 0 failed, 0 skipped, 4 warnings, 601.8 s; 0 `*.pyc` under `tasks/`; no tracked change |
| Focused: canary + cross-system + campaign-readiness | **60 passed** (1 + 58 + 1). Canary receipt: historical hash before = after, `unexpected_thread_errors: 0`, every native-run / report / result match after restart `true`, interrupted positions 0 and 1 (seeds 1000, 1001), resumed position 1 (seed 1001) |
| Web typecheck / build | pass / pass (same asset hashes) |
| `reports/runs.sqlite` sha256 before / after | `42b6dad8…838ced` / `42b6dad8…838ced` |

## 5. ORACLE audit state

Unchanged by the promotion: 15 HEALTHY, 2 NEEDS_REVIEW (`fix-list-dedup`, `refactor-order-validation`), 7 PROVISIONAL
(`async-batched`, `async-first-success`, `async-gather-bounded`, `grid-paths`, `merge-intervals`, `top-k-frequent`,
`two-sum-indices`), 0 INVALID; hidden-test isolation UNVERIFIABLE for all 24 tasks (trusted-local execution model).

## 6. Campaign preparation state

**Real 720-run campaign has NOT started.** The campaign is fully prepared and waits for the project owner's explicit
approval; nothing has been written to its database or ledger (neither exists yet: `init-db` and the first launch
create them).

| Item | State |
|---|---|
| Campaign id | `phase0-post-integrity-v1` |
| Frozen plan | [`campaigns/phase0-post-integrity/manifest.json`](../../campaigns/phase0-post-integrity/manifest.json) — file sha256 `4623eb24b6f000b74d0370fd0a0d91922bcf0bfe8cd9a17ed1cb196aa1ff27e8`, canonical manifest hash `sha256:a3731a401c179cd731c641edf190e5518b1877b4247f2f60c54dd73699c35190` (what the ledger will freeze), built 2026-09-26T15:42:36Z; runtime tag `phase0-integrity-v1` = `7369e67` |
| Matrix | 6 models × 24 tasks × 5 repetitions = **720 runs** (144 cells, 120 runs per model); every task pinned to its current version **and** content digest |
| Phase A (early warning) | **51 cells / 255 runs**: the prior-pass cells on the 18 version-changed tasks — `qwen2.5-coder:7b` 15, `deepseek-coder:6.7b` 11, `qwen3.5:9b` 10, `llama3.2:latest` 8, `qwen2.5-coder:3b` 5, `gemma2:2b` 2 |
| Phase B | 93 cells / 465 runs, prepared, not started |
| Execution | ATLAS Jobs API only (`POST /api/v1/jobs`), one fresh evaluation per (model, task) cell, strictly one at a time; backend `ollama` at `http://127.0.0.1:11434` (real only; mock refused); temperature 0.8; base seed 42 → position *idx* runs with seed 42 + *idx*; request timeout 180 s |
| Evidence scope | `real` **and campaign-owned**: only evaluations of active ledger entries accepted by the one shared acceptance predicate (`validate.assess_cell`) count |
| Campaign database | `reports/phase0-campaign.sqlite`, **clean** strategy (created empty by `init-db`; never `reports/runs.sqlite`; gitignored) |
| Ledger | `reports/phase0-campaign/ledger.json` (gitignored): entries per cell (state, evaluation id, digests and Ollama version at submission/acceptance, code-check and warm-up flags, resume records, halt snapshot, supersessions), launch records with the Ollama inventory, events, disowned evaluations |
| Model availability | Ollama 0.31.1 on this machine has **only `qwen3.5:9b`** (digest `6488c96f…93ea7`, Q4_K_M). `qwen2.5-coder:7b`, `qwen2.5-coder:3b`, `deepseek-coder:6.7b`, `llama3.2:latest` and `gemma2:2b` are **missing**; they were not pulled and nothing was substituted ([inventory](../../campaigns/phase0-post-integrity/model-inventory-2026-09-26.json)). `preflight` refuses to launch until all six are present |
| Operator commands | `python3 -m afa_campaign` (with `PYTHONPATH=campaigns`): `build-manifest`, `derive`, `inventory`, `init-db`, `preflight`, `plan`, `launch` (requires `--confirm phase0-post-integrity-v1`), `resume`, `supersede`, `disown`, `status`, `validate`, `phase-a-report`, `compare-baselines`, `baseline-report`. Runbook: [`docs/campaigns/PHASE0_POST_INTEGRITY_CAMPAIGN.md`](../campaigns/PHASE0_POST_INTEGRITY_CAMPAIGN.md) |

**Tests.** `campaigns/tests`: **309 passed**. Full repository suite on the final tree (clean worktree, `python3 -m pytest -p no:cacheprovider -ra`): **1511
passed** (the 1202 of the release + 309 campaign tests), 0 failed, 0 skipped, 4 warnings, 783.8 s; 0 `*.pyc` under
`tasks/`; no tracked change.

**Independent review.** The tooling went through six rounds of independent adversarial review (separate test
authors, red-team reviewers and documentation fact-checkers working in their own worktrees); every finding was
reproduced before it was fixed and each fix carries a regression test. Among them: model identity by Ollama digest
**and server version** at submission, while running and at acceptance; strictly sequential execution with trial-level
overlap detection; durable (never silently re-accepted) rejections; resumes marked in flight before the request and
settled from the app's own resume events; detection of resumes made outside the tooling; the launcher applying the
validator's own acceptance predicate; an immutable, WAL-aware read of the historical evidence. The sixth round found
only low-severity issues; they were fixed with regression tests and verified by the full suite and dry run 5, without
a further independent round.

**Dry runs** (scratch databases outside the repository, derived campaign ids, `qwen3.5:9b` on Ollama 0.31.1 — the
only roster model installed; never campaign evidence):

| # | Tooling | Campaign id (scratch) | Cells × repetitions | Evaluations (all `succeeded`, `fresh`, backend `ollama`, provenance `real`) | Exercised |
|---|---|---|---|---|---|
| 1 | `09a77ab` | `phase0-post-integrity-dryrun1` | `fix-binary-search`, `sanitize-filename` × 1 | `cd76cccf…` (1/1 passed), `d160fe06…` (0/1) | pause (`--max-evaluations 1`), launcher + app SIGKILL mid-evaluation, same-id recovery |
| 2 | `bc380c9` | `phase0-post-integrity-dryrun2` | `escape-html`, `fix-binary-search` × 1 | `373b466a…` (1/1), `60ea0571…` (1/1) | single launch, validator, reports |
| 3 | `dd32044` | `phase0-post-integrity-dryrun-final` | `escape-html`, `fix-binary-search` × 2 | `158335e0…` (2/2), `071ab786…` (2/2) | the full script of row 5 on the round-4 tooling (identity, server-version and concurrency checks on the real path) |
| 4 | `d9205fd` | `phase0-post-integrity-dryrun-final` | `escape-html`, `fix-binary-search` × 2 | `6b5cd6ed…` (2/2), `04c84b01…` (2/2) | the full script of row 5 on the round-5 tooling |
| 5 | `e094cf8` (tree-identical to the committed tooling `e2d884a`) | `phase0-post-integrity-dryrun-final` | `escape-html` (1.0.1), `fix-binary-search` (1.0.0) × 2 | `1d41a42ba1c9472b8e469b42f40b9dd8` (2/2), `87011caa1fad4a19938c8d3c61d9d331` (2/2) | preflight; `launch` refused without `--confirm` (exit 2); `--max-evaluations 1` pause; `status`; `validate` NOT COMPLETE (exit 1); background launch; SIGKILL of launcher **and** app after position 0 of the second evaluation; app restart → ATLAS startup recovery under the **same id** (`job_reclaimed`), completed position kept, position 1 re-run; relaunch drained it (`drained` 1); every entry recorded digest `6488c96f…` and Ollama 0.31.1 at submission and acceptance, code check and warm-up `True`; `validate` COMPLETE (exit 0); `phase-a-report`, `compare-baselines`, `baseline-report` written |

In every dry run and test session `reports/runs.sqlite` kept sha256 `42b6dad8…838ced` and no tracked file changed.
Dry run 5 ran on the tooling tree that is committed here.

**Committed vs not committed.** Committed: the tooling, its tests, the frozen plan, the preparation-time inventory,
the runbook and this receipt (paths `campaigns/`, `docs/`, `pyproject.toml` only; `afa_api/`, `runner/`, `kernel/`,
`tasks/` are identical to the tag). Never committed: campaign or scratch databases, ledgers, logs, Ollama caches or
lock files.

**Push.** `master` is fast-forwarded from `7369e67` to the campaign-preparation commits (this receipt included) and
pushed to `origin` together with the annotated tag `phase0-integrity-v1` (→ `7369e67`), without force.

**Next step (needs explicit approval).** Pull the five missing models (exact names), record the pre-launch inventory,
`init-db`, start `afa_app.py` on the campaign database, `preflight`, then
`launch --phase A --confirm phase0-post-integrity-v1`, review the Phase-A report, and only then Phase B.

## 7. Environment notes (this machine)

* The first `git` on `PATH` (`/usr/local/bin/git`, an Intel-only Homebrew build) no longer runs after the macOS 27
  upgrade ("bad CPU type"); interactive zsh silently falls back to `/usr/bin/git`, but non-interactive tools do not.
  Verification scripts used `/usr/bin/git`; the campaign tooling selects a git that actually runs (`AFA_GIT`
  overrides). The system was not modified.
* The session scratch directory from the release-hardening mission had been cleared; the pre/post audit comparison
  therefore used the committed baseline JSON, which holds every per-check result.
