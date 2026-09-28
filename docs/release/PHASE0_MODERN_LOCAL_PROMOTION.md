# Modern Local Benchmark v1 — promotion receipt

> **`phase0-modern-local-v1` is a frozen benchmark release.** 5 models × 24 tasks × 5 repetitions = **600 accepted
> real runs** (120 campaign-owned evaluations), run locally through Ollama 0.31.1 on an Apple M4 Max with 36 GiB, on
> the Phase-0 runtime `phase0-integrity-v1`. The release freezes **benchmark results, not model weights**; none of the
> five models is installed any more, and the evidence validates without them.

## 1. What was promoted

| | |
|---|---|
| Campaign source | `campaign/phase0-modern-local-v1` @ **`b4d338149d176d592fb6d59bf11ee1ee9cc471c9`** (= `origin`, verified before anything changed), plus this promotion commit (report caveat wording + this receipt; documentation only) |
| `master` before | `296e82a9c6219b499dcb794718e9660a170451d6` (= `origin/master`; an ancestor of the campaign branch, no independent commits) |
| Strategy | **fast-forward** — the 16 campaign commits and this commit are preserved as they are; no squash, no merge commit |
| Result tag | **`phase0-modern-local-v1`** (annotated) → the promotion commit on `master` |
| Runtime | tag `phase0-integrity-v1` → `7369e67e1ceb4b2a566986f247961f8a63f99567`; `afa_api/`, `runner/`, `kernel/`, `tasks/` byte-identical to it |
| Historical evidence | `reports/runs.sqlite` sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced`, unchanged (same git blob at the tag, old master and the campaign branch) |

## 2. Pre-promotion verification

Four independent read-only verifiers and a completeness critic checked the campaign branch at `b4d3381` against
primary evidence — the committed artifacts, git objects and a byte-identical copy of the campaign database and ledger
(opened with `mode=ro&immutable=1`); none of them trusted a number from the report or the mission text.

| Gate | Result |
|---|---|
| Diff `296e82a..b4d3381` | 35 files (25 added, 10 modified, 0 deleted), every one classified: campaign tooling (9), its tests (2), the modern-local manifest, 5 receipts × json + md, completeness receipt, official leaderboard json + md, `SHA256SUMS`, 7 storage inventories / audit log, the campaign report, the old campaign's status banner (now CANCELLED). No weights, databases, ledgers, logs or home paths |
| Runtime freeze | tree ids of `afa_api` `8bed62d…`, `runner` `22d57c0…`, `kernel` `b6c72c6…`, `tasks` `c3604fa…` identical at the tag, old master and the branch; no branch commit touches them, `afa_app.py`, `integrity/`, `web/` or `db/` |
| Task pins | the manifest's 24 task versions and content digests equal the task pack at the tag (recomputed two independent ways); every one of the 600 evaluation trials carries them |
| Frozen plan | manifest canonical sha256 `a89bf89f…71b4db6d1` — the same value in the ledger, all five receipts, the completeness receipt and the leaderboard |
| Completeness | `completeness-receipt-all.json`: `complete: true`, `problems: []`, 5 models complete, 120 cells, 600 accepted runs (24 × 5 per model); 0 missing, 0 extra, 0 untracked, 0 disowned, 0 superseded; provenance `real` 600, 0 mock / synthetic, 0 conflicts, 0 legacy; `backend_kind = ollama` for all 600 |
| Model receipts | M1–M5 each 24/24 cells and 120/120 accepted runs, pinned model digest at submission and acceptance, Ollama 0.31.1; `.md` equals `.json`; totals equal the leaderboard rows |
| Leaderboard | JSON and Markdown consistent (ranks, passes, intervals, coverage, timeouts, task matrix, domain profiles); Wilson 95 % intervals recomputed (z = 1.96); order = the kernel's ranking by Wilson lower bound (`kernel/afa_kernel/ranking.py` `rank_by_lcb`, reached through `analysis.official_baseline` → `runner/afa_runner/report.py` `leaderboard`); flagged OFFICIAL |
| Canonical re-derivation | `validate --phase all` (exit 0, COMPLETE) and `baseline-report` (exit 0) re-run with the campaign tooling on the evidence copies reproduce the committed completeness receipt and leaderboard exactly, apart from `generated_at` and path sanitization; database and ledger hashes unchanged by the run |
| Database cross-check | 120 evaluation jobs (campaign-named, succeeded, fresh), 600 trials, 600 runs, 600 scores, 600 diffs, 8,949 test results; `integrity_check` ok; sha256 `04babe7d…a43bbe36f` |
| `SHA256SUMS` | all 20 committed copies and all 20 runtime originals verify; copies differ from originals only by `<repo>` / `~` path sanitization |
| Storage outcome | every target pulled or reused at its pinned digest and removed only after its receipt was frozen; all five absent at the end; the final validation ran with no benchmark model installed |
| Tests (clean worktree at `b4d3381`) | **476 passed**, 0 failed, 0 skipped: campaign tooling 417, Phase-0 acceptance canary 1, cross-system ORACLE + ATLAS 58 (475 s); historical hash unchanged; no tracked change |

Verified official leaderboard:

| rank | model | passes | pass rate | Wilson 95 % | coverage | timeouts (full 180 s request) | agent errors | mean final score |
|---|---|---|---|---|---|---|---|---|
| 1 | `gpt-oss:20b` | 96 / 120 | 0.800 | [0.720, 0.862] | 24/24 | 0 (0) | 0 | 0.961 |
| 2 | `devstral-small-2:24b` | 71 / 120 | 0.592 | [0.502, 0.675] | 24/24 | 5 (0) | 0 | 0.829 |
| 3 | `qwen3.5:9b` | 40 / 120 | 0.333 | [0.255, 0.422] | 24/24 | 30 (19) | 0 | 0.481 |
| 4 | `qwen3-coder:30b` | 18 / 120 | 0.150 | [0.097, 0.225] | 24/24 | 0 (0) | 0 | 0.184 |
| 5 | `qwen3.6:27b` | 11 / 120 | 0.092 | [0.052, 0.157] | 24/24 | 105 (83) | 0 | 0.122 |

## 3. Result caveats (fixed in this commit)

The verifiers blocked promotion on one gate: the report did not yet carry the required interpretive framing and made
causal claims the evidence cannot support. This commit corrects `docs/campaigns/PHASE0_MODERN_LOCAL_CAMPAIGN.md` only:

- **Qwen3-Coder 30B-A3B — protocol sensitivity.** 96 of 120 runs produced no applied edit. In a diagnosed
  reproduction the model wrote a correct fix but omitted AgentForge v1's required opening code fence; the campaign
  keeps no raw responses, so that cause is not established for every one of the 96. *Protocol sensitivity was
  demonstrated in a diagnosed case; the overall result reflects both coding performance and compliance with AgentForge
  v1's output contract.* The 15 % pass rate is not a general statement about the model's coding ability.
- **Qwen3.6 27B — latency constrained.** 105 of 120 runs were classified as timeouts, 83 of them full 180-second
  request timeouts. *Performance under the fixed local latency budget was heavily constrained* — on this machine, under
  the uniform protocol; not a general capability conclusion.
- **Historical results are not directly comparable**: 18 of the 24 task definitions changed and the historical runs
  predate the current evaluation-integrity system (the historical database records no evaluation trials, task digests
  or backend provenance).
- A personal external-volume path was redacted, and one unverifiable diagnostic detail (token counts) was dropped.

The committed result artifacts under `campaigns/phase0-modern-local-v1/results/` were not changed; the leaderboard
files carry no interpretive text and rely on the report for these caveats.

## 4. Freeze policy

From the tag on, `campaigns/phase0-modern-local-v1/results/` and the plan `campaigns/phase0-modern-local-v1/manifest.json`
are immutable. A later factual correction keeps every original artifact byte-for-byte and adds an explicit, versioned
correction (a new file that names what it corrects and why, and a new tag); nothing in the release is rewritten in
place. The runtime database and ledger stay outside git (`reports/phase0-modern-local.sqlite`,
`reports/phase0-modern-local/ledger.json`, sha256 `04babe7d…a43bbe36f` and `8450e48f…98910a`).

## 5. Non-blocking observations

- The launcher's runtime-freeze check covers `afa_api/`, `runner/`, `kernel/`, `tasks/`; `examples/` (imported by
  `afa_api/store_load.py`), `afa_app.py`, `db/` and `integrity/` are outside it. All of them are byte-identical from the
  tag to this release, so nothing drifted; a future campaign should widen the check.
- The campaign tooling opens the frozen campaign database read-only but not `immutable`, so `validate` and
  `baseline-report` create or touch its `-shm` / empty `-wal` sidecars; the database file itself never changed.
- Tooling provenance: each model ran at one committed tooling head (report §7); the first M1 smoke fix and the first
  `remove-weights` ran shortly before their commits, as the report discloses; 8 of the 16 campaign commits carry
  `WIP:` subjects, kept as history.

## 6. Post-promotion verification

Recorded in the annotated tag's message: the fast-forwarded `master` is re-checked (campaign ancestry, result hashes,
runtime tree, historical hash) and the focused tests re-run before the tag is created and pushed.
