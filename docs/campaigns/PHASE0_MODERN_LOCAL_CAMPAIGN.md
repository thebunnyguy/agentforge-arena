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
`reports/runs.sqlite` (18 of the 24 tasks changed version since; other runtime, other generation conditions).

## 2. Environment

| | |
|---|---|
| Machine | Apple M4 Max, arm64, 36 GiB unified memory, macOS 27.0 |
| Disk (data volume) | 926 GiB; **4.7 GiB free** at the start of the mission (3.9 GiB when the storage inventory was taken) |
| Ollama | 0.31.1 (`ollama serve` started from the CLI with `OLLAMA_KEEP_ALIVE=60m`; every other server setting is the default and stayed unchanged for the whole campaign; models in `~/.ollama/models`) |
| AgentForge runtime | tag `phase0-integrity-v1` = `7369e67e1ceb4b2a566986f247961f8a63f99567`; `afa_api/`, `runner/`, `kernel/`, `tasks/` checked equal to the tag before every launch |
| Historical evidence | `reports/runs.sqlite` sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced`, checked before the campaign, before every submission, after every model and at the end |

The shell profile exports `OLLAMA_MODEL_PATH=/Volumes/X10 Pro/ollama-cli-models`; that is not an Ollama variable
(Ollama reads `OLLAMA_MODELS`) and the drive was not mounted, so every model lived on the internal disk.

## 3. Storage inventory and cleanup

Initial inventory ([`storage-before.json`](#), kept with the campaign outputs; home paths shown as `~`):

| Runtime | Model | Size | Notes |
|---|---|---|---|
| Ollama | `qwen3.5:9b` | 6.1 GiB | campaign target M1, reused (not re-downloaded) |
| Ollama | `qwen3.6:27b-mlx` | 18.4 GiB | MLX (nvfp4) — authorized for removal |
| Ollama | `nomic-embed-text:latest` | 0.3 GiB | embedding model, kept (not needed for space) |
| Hugging Face cache | `unsloth/Qwen3.6-27B-GGUF` (Q4_K_M) | 15.7 GiB | model weights, kept (space not needed) |
| Hugging Face cache | `openai/clip-vit-base-patch32` | 1.1 GiB | not a benchmark model, never touched |
| LM Studio | `Ministral-3-14B-Reasoning-2512-GGUF` | 11.1 GiB | model weights, kept (space not needed) |

Totals: 8 removals (6 Ollama models, 2 non-Ollama weight directories), **~112 GiB of model weights removed**; free
disk went from 4.7 GiB at the start to 45.1 GiB at the end. Kept untouched: `nomic-embed-text:latest` (Ollama),
`openai/clip-vit-base-patch32` (Hugging Face cache), an empty LM Studio `Qwen2.5-Coder-14B-Instruct-MLX-4bit` directory.
Every pull and removal is also in the committed audit log `campaigns/phase0-modern-local-v1/results/inventories/storage-log.jsonl`.

Every removal is recorded BEFORE it happens — in `reports/phase0-modern-local/inventories/storage-log.jsonl` and,
once the ledger exists, in the ledger's `model_deletions` (model, runtime, digest, size, reason, campaign evidence
status, free space before/after):

| When | Removed | Size | Reason | Evidence status | Free after |
|---|---|---|---|---|---|
| before M1 | `qwen3.6:27b-mlx` (Ollama, MLX nvfp4) | 18.4 GiB | authorized MLX weights; 3.9 GiB free was too low to operate safely and to pull the next target | not a campaign model | 22 GiB |
| during M1 | `unsloth/Qwen3.6-27B-GGUF` (Hugging Face cache, one Q4_K_M GGUF) | 15.7 GiB | macOS swap grew on the same volume during the batch (free space fell from 20 to 12 GiB); clearly model data, re-downloadable, redundant with the Ollama `qwen3.6:27b` target | not a campaign model (outside Ollama) | 27 GiB |
| after M1's receipt | `qwen3.5:9b` (Ollama, campaign target M1) | 6.1 GiB | M1 complete and frozen; disk needed for M2 with headroom | receipt `M1-qwen3.5-9b.json` frozen with 120 accepted runs, re-validated complete | 34 GiB |
| after M2's receipt | `gpt-oss:20b` (Ollama, campaign target M2) | 12.8 GiB | M2 complete and frozen; disk needed for M3 with headroom | receipt `M2-gpt-oss-20b.json` frozen with 120 accepted runs, re-validated complete | 32.9 GiB |
| after M3's receipt | `devstral-small-2:24b` (Ollama, campaign target M3) | 14.1 GiB | M3 complete and frozen; disk needed for M4 with headroom | receipt `M3-devstral-small-2-24b.json` frozen with 120 accepted runs, re-validated complete | 30.6 GiB |
| after M4's receipt | `qwen3-coder:30b` (Ollama, campaign target M4) | 17.3 GiB | M4 complete and frozen; disk needed for the optional M5 with headroom | receipt `M4-qwen3-coder-30b.json` frozen with 120 accepted runs, re-validated complete | 33.8 GiB |
| during M5 | `Ministral-3-14B-Reasoning-2512-GGUF` (LM Studio: Q6_K GGUF + F16 projector GGUF) | 11.2 GiB | machine safety: swap grew ~6 GB in 30 min during the 27B batch and free disk fell to 11 GiB; clearly model data | not a campaign model (outside Ollama) | 22.5 GiB |
| after M5's receipt | `qwen3.6:27b` (Ollama, campaign target M5) | 16.5 GiB | campaign finished; the owner does not require keeping benchmarked weights | receipt `M5-qwen3.6-27b.json` frozen with 120 accepted runs, re-validated complete | 45.1 GiB (swap also shrank) |

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
python3 -m afa_campaign remove-model --model <finished target> --reason "..."   # only if space is needed
python3 -m afa_campaign pull-model --phase M2                        # reuse if installed; digest must equal the pin
python3 -m afa_campaign smoke --phase M2 --confirm phase0-modern-local-v1   # 4 tasks x 1 rep, SCRATCH db (never evidence)
python3 -m afa_campaign preflight --phase M2
python3 -m afa_campaign launch --phase M2 --confirm phase0-modern-local-v1  # 24 evaluations x 5 positions
python3 -m afa_campaign validate --phase M2                          # 24 cells / 120 accepted runs
python3 -m afa_campaign model-receipt --phase M2                     # frozen receipt BEFORE any removal
python3 -m afa_campaign status                                       # campaign progress
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
| Scores | **40/120 passed — pass rate 0.333, Wilson 95% [0.255, 0.422]**; mean final score 0.481; 30 timeouts (19 ran the full 180 s request timeout; each time the model answered the one-token probe afterwards, so they are model behaviour); 0 agent errors |
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
| Install | pulled 23:49 → 00:06 UTC on 2026-09-28 after M2's weights were removed; digest verified against the pin |
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

**Why this coding model scores low — an output-format failure, not a serving fault.** The frozen AgentForge agent
asks every model to answer with `# FILE: <path>` followed by a fenced ```` ```python ```` block holding the complete
file, and its parser (`runner/afa_runner/agents_ollama.py`) applies only complete fenced blocks. Reproduced with the
runtime's own prompt builder and request (temperature 0.8, seeds 42/43, outside the campaign database):
`qwen3-coder:30b` answers `# FILE: <path>`, then the complete file, then a closing fence — **without the opening
fence** — so no block is parsed and no edit is applied; in the reproduced `fix-binary-search` case the code itself
was a correct fix. `/api/generate` and `/api/chat` produced identical prompt-token counts (470 / 511) and identical
output, Ollama reports no output parser or thinking for this model, and every other model got the same prompt and
parser. Under the campaign's rules this is a benchmark outcome of the model under the uniform protocol (it ran
normally and needed no special setting), not `LOCAL_RUNTIME_UNSUPPORTED`; the runtime was not changed. Its score
measures format compliance with AgentForge's agent contract as much as coding ability, and should be read that way.

### M5 (optional) — Qwen3.6 27B (`qwen3.6:27b`) — COMPLETE, ranked

| | |
|---|---|
| Identity | digest `9d5803d493a991af27b9441c098aa56f2ed7bbd260877f075ec09b575c049bc3` = the pin, at submission and acceptance of all 24 cells; qwen35, 27.3B, Q4_K_M (canonical GGUF tag, not the MLX variant); 17.77 GB; Ollama 0.31.1 |
| Install | pulled 01:21 → 01:49 UTC on 2026-09-28 (28 min) after M4's weights were removed; digest verified against the pin |
| Practicality check | smoke passed operationally (4 valid evaluations, 1/4 passed, 2 timeouts); resident model ~20 GB; memory 15–24 % free, swap flat, disk unchanged during the smoke — practical, so the optional batch ran |
| Resources during the batch | memory 13–24 % free throughout, no OOM, no crash; macOS swap grew to ~14–17 GB on the data volume, so an 11.2 GiB LM Studio GGUF was removed (§3) and a watchdog would have stopped the model below 8 GiB free (it never fired; free disk stayed ≥ 11 GiB) |
| Full batch | 24 fresh evaluations, 120 runs, 01:59 → 07:21 UTC on 2026-09-28 (5 h 22 min) |
| Validation | 24/24 cells, **120/120 accepted real runs**, 0 voided, 0 missing, 0 extra, provenance `real` 120 |
| Scores | **11/120 passed — pass rate 0.092, Wilson 95% [0.052, 0.157]**; mean final score 0.122; **105 timeouts** (83 ran the full 180 s request timeout; after each, the model answered the one-token probe, so they are model behaviour — it reasons for longer than the uniform time budget allows); 0 agent errors |
| Receipt | `reports/phase0-modern-local/receipts/M5-qwen3.6-27b.json` (+ `.md`), sha256 `39f381d6e773…`, recorded in the ledger |
| Weights | removed after the receipt; the whole campaign validated **COMPLETE with no benchmark model installed** |

Passes per task: fix-binary-search 4, fix-list-dedup 3, fix-roman-numerals 1, merge-intervals 1, query-builder 1,
refactor-order-validation 1; 0/5 on the other 18 tasks (17 of them timed out on all 5 runs).

## 7. Final cohort, leaderboard and integrity

**Final cohort: all five models completed the full benchmark** — Qwen 3.5 9B, gpt-oss 20B, Devstral Small 2 24B,
Qwen3-Coder 30B-A3B and (optional) Qwen3.6 27B. No model was classified `LOCAL_RESOURCE_LIMIT` or
`LOCAL_RUNTIME_UNSUPPORTED`; none was substituted; no hosted or paid service was used.

**Final run count: 600 accepted real runs** (5 × 24 × 5) in 120 campaign-owned fresh evaluations — 480 from the four
required models (the minimum) + 120 from the optional model.

### OFFICIAL modern local leaderboard (kernel ranking by Wilson 95 % lower bound)

| rank | model | n | pass rate | Wilson 95 % | coverage |
|---|---|---|---|---|---|
| 1 | `gpt-oss:20b` | 120 | 0.800 | [0.720, 0.862] | 24/24 |
| 2 | `devstral-small-2:24b` | 120 | 0.592 | [0.502, 0.675] | 24/24 |
| 3 | `qwen3.5:9b` | 120 | 0.333 | [0.255, 0.422] | 24/24 |
| 4 | `qwen3-coder:30b` | 120 | 0.150 | [0.097, 0.225] | 24/24 |
| 5 | `qwen3.6:27b` | 120 | 0.092 | [0.052, 0.157] | 24/24 |

Domain profiles (pooled pass rate per task domain, weighted by domain membership):

| model | api-design | async-concurrency | backend | performance | security |
|---|---|---|---|---|---|
| `gpt-oss:20b` | 0.97 | 0.64 | 0.87 | 0.95 | 0.56 |
| `devstral-small-2:24b` | 0.75 | 0.24 | 0.69 | 0.68 | 0.44 |
| `qwen3.5:9b` | 0.17 | 0.08 | 0.37 | 0.42 | 0.48 |
| `qwen3-coder:30b` | 0.25 | 0.00 | 0.04 | 0.45 | 0.16 |
| `qwen3.6:27b` | 0.07 | 0.00 | 0.17 | 0.03 | 0.00 |

The full leaderboard, the 24-task × 5-model matrix, per-model domain profiles and the provenance summary are in
`campaigns/phase0-modern-local-v1/results/outputs/modern-local-leaderboard.{json,md}`; the per-model receipts in
`results/receipts/`. **Reading the results:** every model got the same prompt, parser, task pins, temperature, seeds
and 180 s request timeout. Two scores are dominated by that uniform protocol rather than by raw ability:
Qwen3-Coder 30B-A3B's (96/120 answers without the opening code fence the agent contract requires — §6 M4) and
Qwen3.6 27B's (105/120 runs over the time budget — §6 M5). Quantization and architecture differ naturally
(Q4_K_M ×4, MXFP4 for gpt-oss).

### Comparability with the historical baseline

Not directly comparable, and never pooled: the 720 pre-Phase-0 runs used older versions of 18 of the 24 tasks, a
different runtime path and, for some models, other generation settings. Only `qwen3.5:9b` appears in both; its
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
| Historical evidence | `reports/runs.sqlite` sha256 `42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced` — unchanged before the campaign, before every submission, after every model and at the end |

### Committed vs not committed

Committed: the tooling (`campaigns/afa_campaign`), its tests, the frozen plan, this report, and
`campaigns/phase0-modern-local-v1/results/` — the five model receipts, the completeness receipt, the leaderboard and
the storage inventories and audit log, path-sanitized (repository path → `<repo>`, home → `~`; `SHA256SUMS` lists
the runtime originals' and the committed copies' hashes). Never committed: model weights, Ollama or MLX storage, the
campaign and scratch databases, the ledger, logs.

### Free hosted tier

No primary model failed locally, so no hosted substitute was needed or recorded; a free-hosted campaign
(`phase0-modern-free-hosted-v1`) remains a separate, future tier.
