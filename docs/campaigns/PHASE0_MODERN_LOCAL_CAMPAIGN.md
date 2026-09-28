# AgentForge Modern Local Benchmark — `phase0-modern-local-v1`

> **Status: COMPLETE (2026-09-28).** All five roster models — the four required ones and the optional Qwen3.6 27B —
> completed 24 tasks × 5 fresh repetitions: **600 accepted real runs**, validated with **no benchmark model installed**,
> and an **OFFICIAL** modern local leaderboard. The original six-model historical replication campaign
> `phase0-post-integrity-v1` is **cancelled** and was never launched.

Plan: [`campaigns/phase0-modern-local-v1/manifest.json`](../../campaigns/phase0-modern-local-v1/manifest.json) ·
Tooling: `campaigns/afa_campaign` (every terminal: `cd <repo> && export PYTHONPATH=campaigns
AFA_CAMPAIGN_MANIFEST=campaigns/phase0-modern-local-v1/manifest.json`, then `python3 -m afa_campaign <command>`).

## 1. Purpose

A new post-Phase-0 baseline of **modern, locally runnable, zero-cost coding models**: every model runs all 24
AgentForge tasks × 5 fresh repetitions (**120 accepted real runs per model**) through the full ATLAS evaluation
lifecycle on the promoted Phase-0 runtime, on this Mac, through Ollama. Local storage cannot hold the cohort at
once, so the campaign runs **one model at a time**: install or reuse one target, smoke it, benchmark it, validate
and freeze its receipt, then its weights may be removed before the next target is installed. **Model weights are
not benchmark evidence**: the campaign database and ledger are independent of the model files, and every result
stays inspectable — and re-validates — after its model has been deleted.

This cohort is a **new baseline**. It is not directly comparable with the historical pre-Phase-0 runs in
`reports/runs.sqlite` (18 of the 24 task definitions changed version since; the historical runs predate the current evaluation-integrity
system; other runtime, other generation conditions).

## 2. Environment

| | |
|---|---|
| Machine | Apple M4 Max, arm64, 36 GiB unified memory, macOS 27.0 |
| Disk (data volume) | 926 GiB; **3.9 GiB free** when the first storage inventory was taken (2026-09-27T20:05Z; an earlier, unrecorded reading showed ~4.7 GiB) |
| Ollama | 0.31.1 (`ollama serve` started from the CLI with `OLLAMA_KEEP_ALIVE=60m`; every other server setting is the default and stayed unchanged for the whole campaign; models in `~/.ollama/models`) |
| AgentForge runtime | tag `phase0-integrity-v1` = `7369e67e1ceb4b2a566986f247961f8a63f99567`; `afa_api/`, `runner/`, `kernel/`, `tasks/` checked equal to the tag before every launch |
| Historical evidence | `reports/runs.sqlite` sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced`, checked before the campaign, before every submission, after every model and at the end |

The shell profile exports `OLLAMA_MODEL_PATH=<external volume>/ollama-cli-models`; that is not an Ollama variable
(Ollama reads `OLLAMA_MODELS`) and the drive was not mounted, so every model lived on the internal disk.

## 3. Storage inventory and cleanup

Initial inventory ([`storage-before.json`](../../campaigns/phase0-modern-local-v1/results/inventories/storage-before.json), committed path-sanitized; home paths shown as `~`):

| Runtime | Model | Size | Notes |
|---|---|---|---|
| Ollama | `qwen3.5:9b` | 6.1 GiB | campaign target M1, reused (not re-downloaded) |
| Ollama | `qwen3.6:27b-mlx` | 18.4 GiB | MLX (nvfp4) — authorized for removal |
| Ollama | `nomic-embed-text:latest` | 0.3 GiB | embedding model, kept (not needed for space) |
| Hugging Face cache | `unsloth/Qwen3.6-27B-GGUF` (Q4_K_M) | 15.7 GiB | model weights; initially kept, removed during M1 |
| Hugging Face cache | `openai/clip-vit-base-patch32` | 1.1 GiB | not a benchmark model, never touched |
| LM Studio | `Ministral-3-14B-Reasoning-2512-GGUF` | 11.1 GiB | model weights; initially kept, removed during M5 |

Totals: 8 removals (6 Ollama models, 2 non-Ollama weight directories), **~112 GiB of model weights removed**; free
disk went from 3.9 GiB (first recorded inventory) to 45.1 GiB at the end. Kept untouched: `nomic-embed-text:latest` (Ollama),
`openai/clip-vit-base-patch32` (Hugging Face cache), an empty LM Studio `Qwen2.5-Coder-14B-Instruct-MLX-4bit` directory.
Every pull and removal is also in the committed audit log `campaigns/phase0-modern-local-v1/results/inventories/storage-log.jsonl`.

Every removal is recorded BEFORE it happens in `reports/phase0-modern-local/inventories/storage-log.jsonl`, the
complete record (model, runtime, digest, size, reason, campaign evidence status, free space before/after). The five
campaign-target removals are also in the ledger's `model_deletions`. The MLX removal predates the ledger (created
2026-09-27T20:45:58Z). The two non-Ollama removals are only in the storage log: a running launch held the ledger lock,
so they were not copied into the ledger (logged as `remove-weights-note`).

| When | Removed | Size | Reason | Evidence status | Free after |
|---|---|---|---|---|---|
| before M1 | `qwen3.6:27b-mlx` (Ollama, MLX nvfp4) | 18.4 GiB | authorized MLX weights; 3.9 GiB free was too low to operate safely and to pull the next target | not a campaign model | 22.3 GiB |
| during M1 | `unsloth/Qwen3.6-27B-GGUF` (Hugging Face cache, one Q4_K_M GGUF) | 15.7 GiB | macOS swap grew on the same volume during the batch (free space fell to 11.6 GiB); clearly model data, re-downloadable, redundant with the Ollama `qwen3.6:27b` target | not a campaign model (outside Ollama) | 27.3 GiB |
| after M1's receipt | `qwen3.5:9b` (Ollama, campaign target M1) | 6.1 GiB | M1 complete and frozen; disk needed for M2 with headroom | receipt `M1-qwen3.5-9b.json` frozen with 120 accepted runs, re-validated complete | 33.5 GiB |
| after M2's receipt | `gpt-oss:20b` (Ollama, campaign target M2) | 12.8 GiB | M2 complete and frozen; disk needed for M3 with headroom | receipt `M2-gpt-oss-20b.json` frozen with 120 accepted runs, re-validated complete | 32.9 GiB |
| after M3's receipt | `devstral-small-2:24b` (Ollama, campaign target M3) | 14.1 GiB | M3 complete and frozen; disk needed for M4 with headroom | receipt `M3-devstral-small-2-24b.json` frozen with 120 accepted runs, re-validated complete | 30.6 GiB |
| after M4's receipt | `qwen3-coder:30b` (Ollama, campaign target M4) | 17.3 GiB | M4 complete and frozen; disk needed for the optional M5 with headroom | receipt `M4-qwen3-coder-30b.json` frozen with 120 accepted runs, re-validated complete | 33.8 GiB |
| during M5 | `Ministral-3-14B-Reasoning-2512-GGUF` (LM Studio: GGUF weights + GGUF projector) | 11.1 GiB (11.2 GiB freed) | machine safety: swap grew ~6 GB in 30 min during the 27B batch and free disk fell to 11 GiB; clearly model data | not a campaign model (outside Ollama) | 22.5 GiB |
| after M5's receipt | `qwen3.6:27b` (Ollama, campaign target M5) | 16.5 GiB | campaign finished; the owner does not require keeping benchmarked weights | receipt `M5-qwen3.6-27b.json` frozen with 120 accepted runs, re-validated complete | 45.1 GiB (from 22.1; swap also shrank) |

The two non-Ollama removals ran while a campaign trial was in flight (the tool then had no active-evaluation check;
it now refuses unless `--during-batch` is passed, which records the overlap). The Hugging Face removal
(21:38:17–21:38:21Z) fell inside `qwen3.5:9b | paginator` position 4, which was already 151 s into its budget and
ended as a full 180 s timeout; the LM Studio removal (02:31:39–02:31:57Z) fell inside `qwen3.6:27b | async-retry`
position 0, also a full 180 s timeout, as were all five positions of that cell. Neither removal touched the model
being served, the campaign database or the ledger; their effect on those two runs is nil or marginal.

## 4. Campaign configuration (frozen)

| | |
|---|---|
| Campaign id | `phase0-modern-local-v1` (plan kind `sequential-local`) |
| Runtime | `phase0-integrity-v1` (`7369e67`) |
| Backend | `ollama` at `http://127.0.0.1:11434` (local only; no hosted or paid fallback) |
| Mode | `fresh` for every evaluation |
| Generation | temperature 0.8; base seed 42 → position *idx* uses seed 42 + *idx* (42…46); request timeout 180 s; identical for every model |
| Request | the runtime's `OllamaAgent` calls `/api/generate` with only temperature and seed — context length, thinking and every other setting are the Ollama server's defaults for that model |
| Tasks | all 24, each pinned to its current version **and** content digest (same pins as the Phase-0 release) |
| Granularity | one fresh ATLAS evaluation per (model, task) cell, 5 repetitions: 24 evaluations / 120 runs per model |
| Campaign DB / ledger | `reports/phase0-modern-local.sqlite` (clean), `reports/phase0-modern-local/ledger.json` — gitignored |

Roster (identities resolved from the Ollama registry before any download and pinned in the plan; a model whose
installed digest differs from its pin is never benchmarked):

| Phase | Logical model | Ollama tag | Family / params / quantization | Download | Pinned digest |
|---|---|---|---|---|---|
| M1 | Qwen 3.5 9B | `qwen3.5:9b` | qwen35 / 9.7B / Q4_K_M | 6.59 GB | `6488c96fa5fa…` |
| M2 | gpt-oss 20B | `gpt-oss:20b` | gptoss / 20.9B / MXFP4 | 13.79 GB | `17052f91a42e…` |
| M3 | Devstral Small 2 24B | `devstral-small-2:24b` | mistral3 / 24.0B / Q4_K_M | 15.18 GB | `24277f07f62d…` |
| M4 | Qwen3-Coder 30B-A3B | `qwen3-coder:30b` | qwen3moe (30B-A3B MoE) / 30.5B / Q4_K_M | 18.56 GB | `06c1097efce0…` |
| M5 (optional) | Qwen3.6 27B | `qwen3.6:27b` | qwen35 / 27.3B / Q4_K_M | 17.77 GB | `9d5803d493a9…` |

Notes on identity: Ollama publishes Qwen3-Coder 30B-A3B as `qwen3-coder:30b` (= `latest`; there is no `30b-a3b`
tag); the config blob confirms the `qwen3moe` 30.5B model. For Qwen3.6 27B the canonical GGUF tag `qwen3.6:27b`
is used, not the MLX variant that was installed, so that the cohort shares the Q4-class GGUF runtime path. The 80B
Qwen3-Coder-Next is deliberately out of scope.

## 5. Operating procedure (per model)

```bash
python3 -m afa_campaign storage-inventory --label before-M2          # disk + Ollama + other model weights
python3 -m afa_campaign remove-model --model <finished target> --reason "..." --confirm phase0-modern-local-v1   # only if space is needed
python3 -m afa_campaign remove-weights --path <HF / LM Studio model dir> --reason "..." --confirm phase0-modern-local-v1   # non-Ollama weights, only if clearly model data and needed
python3 -m afa_campaign pull-model --phase M2                        # reuse if installed; digest must equal the pin
python3 -m afa_campaign smoke --phase M2 --confirm phase0-modern-local-v1   # 4 tasks x 1 rep, SCRATCH db (never evidence)
python3 -m afa_campaign preflight --phase M2
python3 -m afa_campaign launch --phase M2 --confirm phase0-modern-local-v1  # 24 evaluations x 5 positions
python3 -m afa_campaign validate --phase M2                          # 24 cells / 120 accepted runs
python3 -m afa_campaign model-receipt --phase M2                     # frozen receipt BEFORE any removal
python3 -m afa_campaign status                                       # campaign progress
# after the last model:
python3 -m afa_campaign validate --phase all                         # whole cohort; COMPLETE only at >= minimum_ranked_models
python3 -m afa_campaign baseline-report                              # OFFICIAL modern-local-leaderboard.{json,md}
```

The campaign app runs throughout from this checkout: `AFA_DB_PATH="$PWD/reports/phase0-modern-local.sqlite"
AFA_NO_BROWSER=1 python3 afa_app.py` (API + worker, one host, one `TMPDIR`). A model that cannot run locally is
recorded with `classify-model --phase Mx --status LOCAL_RESOURCE_LIMIT|LOCAL_RUNTIME_UNSUPPORTED|NOT_BENCHMARKED
--reason ... --evidence ...` — it leaves the expected cohort and is never ranked or counted as a zero-score model.

## 6. Per-model results

### M1 — Qwen 3.5 9B (`qwen3.5:9b`) — COMPLETE, ranked

| | |
|---|---|
| Identity | digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7` = the pin, at submission and acceptance of all 24 cells; qwen35, 9.7B, Q4_K_M; 6.59 GB; Ollama 0.31.1 (server default context length for this model: 262144) |
| Install | already installed: reused, not downloaded |
| Smoke | the first attempt was halted by a tooling defect (the smoke's own scratch plan demanded a prior smoke; fixed, recorded in the ledger as `halted`); the second attempt passed operationally: 4 evaluations, 1/4 passed, 2 timeouts |
| Full batch | 24 fresh evaluations, 120 runs, 2026-09-27 20:55 → 22:50 UTC (1 h 55 min) |
| Validation | 24/24 cells, **120/120 accepted real runs**, 0 voided, 0 missing, 0 extra, provenance `real` 120 |
| Scores | **40/120 passed — pass rate 0.333, Wilson 95% [0.255, 0.422]**; mean final score 0.481; 30 timeouts (19 ran the full 180 s request timeout, in 13 evaluations; after each of those 13 evaluations the model answered a one-token generation probe, so they are treated as model behaviour; the other 11 exceeded the task's wall-clock limit); 0 agent errors; 22 runs produced no edit |
| Receipt | `reports/phase0-modern-local/receipts/M1-qwen3.5-9b.json` (+ `.md`), sha256 `5924d5768149…`, recorded in the ledger |
| Weights | removed after the receipt (6.1 GiB reclaimed); `validate --phase M1` re-run **without the model installed: COMPLETE** — model weights ≠ benchmark evidence |

Per task (passes / 5): escape-html 5, fix-binary-search 4, fix-list-dedup 4, fix-roman-numerals 4,
sanitize-filename 4, grid-paths 3, mask-secrets 3, merge-intervals 3, two-sum-indices 3, async-timeout 2, paginator 2,
query-builder 1, refactor-order-validation 1, top-k-frequent 1, and 0 on async-batched, async-first-success,
async-gather-bounded, async-retry, expression-evaluator, fix-path-traversal, implement-lru-cache, result-type,
toposort, validate-redirect-url.

Disclosure: independent test agents ran the tooling's test suite on this machine during part of M1's batch (extra
CPU load); from M2 on, tests ran only between batches.

### M2 — gpt-oss 20B (`gpt-oss:20b`) — COMPLETE, ranked

| | |
|---|---|
| Identity | digest `17052f91a42e97930aa6e28a6c6c06a983e6a58dbb00434885a0cf5313e376f7` = the pin, at submission and acceptance of all 24 cells; gptoss, 20.9B, MXFP4; 13.79 GB; Ollama 0.31.1 (server default context length 131072) |
| Install | pulled 2026-09-27 22:57 → 23:08 UTC (10.5 min) after M1's weights were removed; digest verified against the pin |
| Smoke | passed operationally: 4 evaluations, 2/4 passed, no timeouts |
| Full batch | 24 fresh evaluations, 120 runs, 23:09 → 23:49 UTC on 2026-09-27 (39.5 min) |
| Validation | 24/24 cells, **120/120 accepted real runs**, 0 voided, 0 missing, 0 extra, provenance `real` 120 |
| Scores | **96/120 passed — pass rate 0.800, Wilson 95% [0.720, 0.862]**; mean final score 0.961; 0 timeouts; 0 agent errors |
| Receipt | `reports/phase0-modern-local/receipts/M2-gpt-oss-20b.json` (+ `.md`), sha256 `e8fa7809f91a…`, recorded in the ledger |
| Weights | removed after the receipt (12.8 GiB reclaimed); M1 and M2 re-validated **COMPLETE without either model installed** |

Per task (passes / 5): 5/5: async-retry, escape-html, fix-list-dedup, fix-roman-numerals, grid-paths, implement-lru-cache, merge-intervals, paginator, query-builder, result-type, top-k-frequent, two-sum-indices; 4/5: async-timeout, expression-evaluator, fix-binary-search, refactor-order-validation, toposort; 3/5: async-batched, async-first-success, fix-path-traversal, mask-secrets, sanitize-filename; 1/5: async-gather-bounded; 0/5: validate-redirect-url.

### M3 — Devstral Small 2 24B (`devstral-small-2:24b`) — COMPLETE, ranked

| | |
|---|---|
| Identity | digest `24277f07f62db8f9cb68e9dfc679ea1818a7fbac47a50eff0a701d3f645b63c8` = the pin, at submission and acceptance of all 24 cells; mistral3, 24.0B, Q4_K_M; 15.18 GB; Ollama 0.31.1 (server default context length 393216) |
| Install | pulled 2026-09-27 23:49 → 2026-09-28 00:06 UTC (16.6 min) after M2's weights were removed; digest verified against the pin |
| Smoke | passed operationally: 4 evaluations, 2/4 passed, no timeouts |
| Full batch | 24 fresh evaluations, 120 runs, 00:08 → 00:53 UTC on 2026-09-28 (44.6 min) |
| Validation | 24/24 cells, **120/120 accepted real runs**, 0 voided, 0 missing, 0 extra, provenance `real` 120 |
| Scores | **71/120 passed — pass rate 0.592, Wilson 95% [0.502, 0.675]**; mean final score 0.829; 5 timeouts; 0 agent errors |
| Receipt | `reports/phase0-modern-local/receipts/M3-devstral-small-2-24b.json` (+ `.md`), sha256 `270168ed9b4a…`, recorded in the ledger |
| Weights | removed after the receipt (14.1 GiB reclaimed); M1, M2 and M3 re-validated **COMPLETE without their models installed** |

Per task (passes / 5): 5/5: fix-binary-search, fix-roman-numerals, implement-lru-cache, mask-secrets, merge-intervals, paginator, query-builder, refactor-order-validation, two-sum-indices; 4/5: async-timeout, fix-list-dedup, grid-paths, sanitize-filename; 3/5: toposort; 2/5: async-gather-bounded, top-k-frequent; 1/5: escape-html, expression-evaluator, fix-path-traversal; 0/5: async-batched, async-first-success, async-retry, result-type, validate-redirect-url.

### M4 — Qwen3-Coder 30B-A3B (`qwen3-coder:30b`) — COMPLETE, ranked

| | |
|---|---|
| Identity | digest `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca` = the pin, at submission and acceptance of all 24 cells; qwen3moe (30B-A3B MoE), 30.5B, Q4_K_M; 18.56 GB; Ollama 0.31.1 (server default context length 262144) |
| Install | pulled 00:54 → 01:04 UTC on 2026-09-28 (11 min) after M3's weights were removed; digest verified against the pin |
| Smoke | passed operationally (4 valid evaluations) but **0/4 passed, every diff empty** — investigated before the batch (below) |
| Full batch | 24 fresh evaluations, 120 runs, 01:08 → 01:20 UTC on 2026-09-28 (12.4 min) |
| Validation | 24/24 cells, **120/120 accepted real runs**, 0 voided, 0 missing, 0 extra, provenance `real` 120 |
| Scores | **18/120 passed — pass rate 0.150, Wilson 95% [0.097, 0.225]**; mean final score 0.184; 0 timeouts; 0 agent errors; **96 of 120 runs produced no edit** (M1 22, M2 1, M3 2) |
| Receipt | `reports/phase0-modern-local/receipts/M4-qwen3-coder-30b.json` (+ `.md`), sha256 `bb816124966b…`, recorded in the ledger |
| Weights | removed after the receipt (17.3 GiB reclaimed); M1–M4 re-validated **COMPLETE without their models installed** |

Passes per task: paginator 5, top-k-frequent 5, grid-paths 4, mask-secrets 4; 0/5 on the other 20 tasks.

**Reading this score — AgentForge v1 output-contract sensitivity, found in a diagnosed case.** The frozen AgentForge agent
asks every model to answer with `# FILE: <path>` followed by a fenced ```` ```python ```` block holding the complete
file, and its parser (`runner/afa_runner/agents_ollama.py`) applies only complete fenced blocks. Reproduced with the
runtime's own prompt builder and request (temperature 0.8, seeds 42/43, outside the campaign database):
`qwen3-coder:30b` answered `# FILE: <path>`, then the complete file, then a closing fence — **without the opening
fence** — so no block was parsed and no edit was applied; in the reproduced `fix-binary-search` case the code itself
was a correct fix. `/api/generate` and `/api/chat` produced identical prompt-token counts and identical output,
Ollama reports no output parser or thinking for this model, and every other model got the same prompt and
parser. Under the campaign's rules this is a benchmark outcome of the model under the uniform protocol (it ran
normally and needed no special setting), not `LOCAL_RUNTIME_UNSUPPORTED`; the runtime was not changed.
Protocol sensitivity was demonstrated in a diagnosed case; the overall result reflects both coding performance and
compliance with AgentForge v1's output contract. The 15 % pass rate is not a general statement about Qwen3-Coder's
coding ability.
The campaign stores no response text, so the cause of each of the 96 empty diffs is not individually verified; the
missing opening fence is the cause found in the diagnosed case. (The diagnostic ran outside the campaign against the
then-installed model; its prompts, responses and token counts were not persisted and are not part of the committed
evidence — only a short operator note was kept outside the repository.)

### M5 (optional) — Qwen3.6 27B (`qwen3.6:27b`) — COMPLETE, ranked

| | |
|---|---|
| Identity | digest `9d5803d493a991af27b9441c098aa56f2ed7bbd260877f075ec09b575c049bc3` = the pin, at submission and acceptance of all 24 cells; qwen35, 27.3B, Q4_K_M (canonical GGUF tag, not the MLX variant); 17.77 GB; Ollama 0.31.1 (Ollama reported no default context length in the model details) |
| Install | pulled 01:21 → 01:49 UTC on 2026-09-28 (28 min) after M4's weights were removed; digest verified against the pin |
| Practicality check | smoke passed operationally (4 valid evaluations, 1/4 passed, 2 timeouts); resident model 17.3 GB (`ollama ps`: 17,269,050,571 bytes); system memory free 84 % before the smoke and 17 % after it, swap used 5.4 → 5.7 GB of 6 GB (recorded in the smoke record) — practical, so the optional batch ran |
| Resources during the batch | memory 13–24 % free throughout, no OOM, no crash; macOS swap grew to ~14–17 GB on the data volume, so an 11.1 GiB LM Studio GGUF was removed (§3) and a watchdog would have stopped the model below 8 GiB free (it never fired; free disk stayed ≥ 11 GiB) — operator monitoring, not persisted; the storage log records 11.3 GiB free at 02:31Z before the LM Studio removal and 22.1 GiB before the final removal |
| Full batch | 24 fresh evaluations, 120 runs, 01:59 → 07:21 UTC on 2026-09-28 (5 h 22 min) |
| Validation | 24/24 cells, **120/120 accepted real runs**, 0 voided, 0 missing, 0 extra, provenance `real` 120 |
| Scores | **11/120 passed — pass rate 0.092, Wilson 95% [0.052, 0.157]**; mean final score 0.122; **105 timeouts** (83 ran the full 180 s request timeout, in 20 evaluations; after each of those 20 evaluations the model answered a one-token generation probe, so they are treated as model behaviour; the other 22 answered within 180 s but exceeded the task's wall-clock limit — its runs took longer than the uniform time budget allows); 0 agent errors; 83 runs produced no edit |
| Receipt | `reports/phase0-modern-local/receipts/M5-qwen3.6-27b.json` (+ `.md`), sha256 `39f381d6e773…`, recorded in the ledger |
| Weights | removed after the receipt (16.5 GiB of weights; free disk rose 22.1 → 45.1 GiB as swap also shrank); the whole campaign validated **COMPLETE with no benchmark model installed** |

Passes per task: fix-binary-search 4, fix-list-dedup 3, fix-roman-numerals 1, merge-intervals 1, query-builder 1,
refactor-order-validation 1; 0/5 on the other 18 tasks (17 of them timed out on all 5 runs).

**Reading this score.** Performance under the fixed local latency budget was heavily constrained. 105 of 120 runs were
classified as timeouts, 83 of them full 180-second request timeouts, on this machine under the uniform protocol. The
score is not a general conclusion about Qwen3.6 27B's capability.

## 7. Final cohort, leaderboard and integrity

**Final cohort: all five models completed the full benchmark** — Qwen 3.5 9B, gpt-oss 20B, Devstral Small 2 24B,
Qwen3-Coder 30B-A3B and (optional) Qwen3.6 27B. No model was classified `LOCAL_RESOURCE_LIMIT` or
`LOCAL_RUNTIME_UNSUPPORTED`; none was substituted; no hosted or paid service was used.

**Final run count: 600 accepted real runs** (5 × 24 × 5) in 120 campaign-owned fresh evaluations — 480 from the four
required models (the minimum) + 120 from the optional model.

### OFFICIAL modern local leaderboard (kernel ranking by Wilson 95 % lower bound)

| rank | model | n | pass rate | Wilson 95 % | coverage | timeouts (full 180 s request) | agent errors |
|---|---|---|---|---|---|---|---|
| 1 | `gpt-oss:20b` | 120 | 0.800 | [0.720, 0.862] | 24/24 | 0 (0) | 0 |
| 2 | `devstral-small-2:24b` | 120 | 0.592 | [0.502, 0.675] | 24/24 | 5 (0) | 0 |
| 3 | `qwen3.5:9b` | 120 | 0.333 | [0.255, 0.422] | 24/24 | 30 (19) | 0 |
| 4 | `qwen3-coder:30b` | 120 | 0.150 | [0.097, 0.225] | 24/24 | 0 (0) | 0 |
| 5 | `qwen3.6:27b` | 120 | 0.092 | [0.052, 0.157] | 24/24 | 105 (83) | 0 |

Domain profiles (pooled pass rate per task domain, weighted by domain membership):

| model | api-design | async-concurrency | backend | performance | security |
|---|---|---|---|---|---|
| `gpt-oss:20b` | 0.975 | 0.640 | 0.872 | 0.950 | 0.560 |
| `devstral-small-2:24b` | 0.750 | 0.240 | 0.688 | 0.675 | 0.440 |
| `qwen3.5:9b` | 0.175 | 0.080 | 0.368 | 0.425 | 0.480 |
| `qwen3-coder:30b` | 0.250 | 0.000 | 0.040 | 0.450 | 0.160 |
| `qwen3.6:27b` | 0.075 | 0.000 | 0.168 | 0.025 | 0.000 |

The full leaderboard, the 24-task × 5-model matrix, per-model domain profiles and the provenance summary are in
`campaigns/phase0-modern-local-v1/results/outputs/modern-local-leaderboard.{json,md}` (regenerated after the final
review from the unchanged database and ledger to add the timeout and agent-error columns); the per-model receipts in
`results/receipts/`. **Reading the results:** every model got the same prompt, parser, task pins, temperature, seeds
and 180 s request timeout. Two scores must be read against that uniform protocol, not as general capability conclusions:
Qwen3-Coder 30B-A3B's (96/120 runs produced no edit; the missing opening code fence reproduced in §6 M4 is the
cause found in the diagnosed case — the campaign stores no response text, so the cause of each of the 96 is not
individually verified) and Qwen3.6 27B's (105/120 runs classified as timeouts, 83 of them full 180 s request timeouts —
§6 M5). Protocol sensitivity was demonstrated in a diagnosed case; the overall result reflects both coding performance
and compliance with AgentForge v1's output contract. Performance under the fixed local latency budget was heavily
constrained. Quantization and architecture differ naturally
(Q4_K_M ×4, MXFP4 for gpt-oss).

### Comparability with the historical baseline

Not directly comparable, and never pooled: the 720 pre-Phase-0 runs used older versions of 18 of the 24 tasks, a
different runtime path and, for some models, other generation settings, and they predate the current evaluation-integrity
system (the historical database records no evaluation trials, task digests or backend provenance). Only `qwen3.5:9b`
appears in both; its
historical 40/120 at temperature 0.6 and its new 40/120 at 0.8 are coincidentally equal counts on different
benchmark definitions.

### Integrity

| Check | Result |
|---|---|
| Accepted runs | 600 / 600 planned; 120 per model; 5 per cell; 0 missing, 0 extra, 0 untracked, 0 disowned, 0 superseded |
| Provenance | `real` 600; **0 mock / synthetic**, **0 conflicts**, 0 legacy; `backend_kind = ollama` for every run |
| Task pack | every run at the frozen current version and content digest (checked in every evaluation snapshot, at every submission and by the validator); no drift |
| Model identity | every cell's digest at submission and at acceptance = its pinned registry digest; Ollama server 0.31.1 for every cell; no identity or concurrency violation |
| Runtime | `afa_api/`, `runner/`, `kernel/`, `tasks/` equal to `phase0-integrity-v1` at every launch (code check recorded per cell) |
| Model weights ≠ evidence | each model re-validated COMPLETE after its weights were removed; the final `validate --phase all` ran with none of them installed |
| Campaign DB | `reports/phase0-modern-local.sqlite` (gitignored): 120 evaluations, 600 trials, 600 runs, 600 scores, 600 diffs, 8,949 test results; `PRAGMA integrity_check` ok; WAL checkpointed; sha256 `04babe7db1b8bdffbf8f92c3d3859f50c7cb05393ee5c1dd74cc724a43bbe36f` |
| Ledger | `reports/phase0-modern-local/ledger.json` (gitignored), sha256 `8450e48f91802e92972713e336f4f9ef5eea882f7e84a4a136bfe84dbd98910a` at freezing |
| Tooling provenance | each model's launches ran at one committed tooling head — M1 `cfa9025`, M2 `7d58623`, M3 `58c8745`, M4 `4955f16`, M5 `b79ea47`; the acceptance code (`launcher.py`, `validate.py`, `ledger.py`, `analysis.py`, `status.py`) is byte-identical from `cfa9025` to the final campaign commit `56daab5` (later commits changed only lifecycle commands, the CLI and a manifest type check). Disclosed gaps: the passing M1 smoke (20:46:36Z) ran on the uncommitted fix later committed as `cfa9025` (20:54:54Z), and the first `remove-weights` (21:38:17Z) ran 12 s before its commit `411e7f7`; smokes and storage actions did not record a tooling revision at the time (they do now) |
| Historical evidence | `reports/runs.sqlite` sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` — unchanged before the campaign, before every submission, after every model and at the end (the main file and its empty WAL are unchanged; its `-shm` sidecar, which is not evidence, was touched by non-immutable opens at 2026-09-27T22:52Z and again at 2026-09-28T08:01:29Z) |

### Final review and post-campaign tooling fixes

An independent read-only fact-check of this report and a red-team review of the tooling ran after the last model.
The report corrections are applied above. The tooling fixes landed after all 600 runs were accepted; none changes the
acceptance predicate, and every committed result was regenerated from the same evidence (the campaign database and
ledger are unchanged by them):

- a plan derived from the campaign plan with `derive` (a rehearsal subset; `derive` never sets the explicit
  `model_files_owner` opt-in) can no longer pull, remove, classify or remove weights — under its partial roster the
  campaign's unfinished targets would look unowned;
- `remove-weights` counts only weight files (by suffix, or ≥ 64 MiB Hugging Face `blobs/`) plus an allow-list of model
  metadata, refuses any other file, refuses while campaign evaluations or a smoke app are live unless `--during-batch`
  (which records the overlap), records the tooling revision, records a part-way failure as `PARTIAL`, and copies its
  record into the ledger without the event-name collision that would have crashed that copy (never reached in this
  campaign: both copies were refused by the launcher's lock). It now has regression tests;
- `validate --phase all` reports a sequential cohort below `minimum_ranked_models` as incomplete (exit 1);
- a reissued model receipt records the renamed superseded file and its sha256 (no receipt was reissued here);
- the leaderboard now shows each model's timeouts, full-request timeouts and agent errors, and names the pinned
  registry digests as the source of model identity; launches record whether the tooling tree was dirty.

### Committed vs not committed

Committed: the tooling (`campaigns/afa_campaign`), its tests, the frozen plan, this report, and
`campaigns/phase0-modern-local-v1/results/` — the five model receipts, the completeness receipt, the leaderboard and
the storage inventories and audit log, path-sanitized (repository path → `<repo>`, home → `~`; `SHA256SUMS` lists
the runtime originals' and the committed copies' hashes). Never committed: model weights, Ollama or MLX storage, the
campaign and scratch databases, the ledger, logs.

### Free hosted tier

No primary model failed locally, so no hosted substitute was needed or recorded; a free-hosted campaign
(`phase0-modern-free-hosted-v1`) remains a separate, future tier.
