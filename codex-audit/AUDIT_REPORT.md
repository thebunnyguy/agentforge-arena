# AgentForge Arena Hardcore Evaluation Report

**Audit date:** 2026-06-20  
**Audited commit:** `798a5b3d7aba74c3a95e51119983b2d75091161c`  
**Branch/remote:** `master`, exactly synchronized with `origin/master` after `git fetch --prune` (ahead 0, behind 0)  
**Audit posture:** external/read-only evaluation. No project code was fixed and nothing was committed.

## Executive verdict

- **Overall grade: 66 / 100**
- **Current maturity: research tool** — usable as a trusted-local experimental harness, not reliable enough for an unqualified public benchmark or untrusted agents.
- **Biggest strength:** the deterministic scoring kernel, raw DB-to-report projection, and broad automated test suite are substantially better than the average prototype.
- **Biggest weakness:** the benchmark confuses “passes the present hidden assertions” with “satisfies the written task contract,” and its real-agent run provenance is incomplete.
- **Most dangerous unresolved risk:** an arbitrary in-process `Agent` receives a `Task` containing absolute `reference_dir` and `task_dir` paths and runs with host privileges. It can read the reference/hidden tests, access the network/filesystem, and bypass the intended evaluation boundary.
- **Next mandatory step:** ship a pinned, network-disabled agent/grader isolation design with a sanitized public task view, fix the two demonstrated task-contract defects, then rerun all five models on the current task versions with every patch, test result, transcript/config, seed, model digest, and timeout classification persisted.

The current leaderboard is a faithful calculation over the committed SQLite rows. It is **not** a fully valid measurement of the written task pack. At least one current functional pass is a demonstrated false positive: qwen-7B's `expression-evaluator` run 4 passes all ten hidden assertions but violates standard left associativity and crashes on supported unary-minus forms. The report's `68/120` is therefore database-correct but contract-contaminated.

## Scorecard

| Dimension | Score /10 | Strict assessment |
|---|---:|---|
| Scoring/math correctness | **7.5** | Kernel arithmetic is correct; overall ranking, timeout behavior, deterministic-run handling, and quality measurement diverge from the full framework. |
| Test suite quality | **8.5** | 366 meaningful tests; strong numeric and clean-room coverage. Seven SQLite resource warnings and important adversarial/integration gaps remain. |
| Task pack quality | **7.0** | All 24 pass structural validation, but validation missed two executable contract defects and several cells are weak/mis-difficultied. |
| Clean-room/security | **5.0** | Good diff allow-list and injection defenses; no untrusted isolation, host dependency pinning, or effective hidden/reference secrecy for arbitrary agents. |
| Real-agent evaluation validity | **7.0** | 600 genuine rows and honest baselines, but 500 runs lack forensic artifacts, 75 rows target stale task versions, and prompt/parser/environment effects are inseparable. |
| Domain coverage | **6.0** | All domains barely clear the display floor; backend dominates and overlapping tags let single idioms drive small domains. |
| Report quality | **7.0** | Useful, honest static overview; failure labels are over-broad and the report has no raw-run/transcript/test drilldown or export. |
| Reproducibility | **6.5** | Tests/demo/report reproduce; model-generation conditions do not. Per-run seeds, three model digests, transcripts, dependency image, and full artifacts are missing. |
| Product usability | **4.5** | Example scripts and HTML are usable; there is no product CLI, API, dashboard, run viewer, or contributor workflow. |
| Documentation accuracy | **7.0** | README/current DEVLOG are substantially reconciled; the full framework still promises behavior the executable harness does not implement. |
| **Total** | **66 / 100** | |

## Critical findings

### P0-1 — Published qwen score contains a demonstrated task-contract false positive

SQLite run `id=550`, `qwen2.5-coder:7b / expression-evaluator / idx=4`, is stored as `G=1`, `T_hidden=1`, `X=1`. Its persisted patch implements same-precedence operators as right-associative and recognizes unary minus only in a subset of positions. Executing the persisted code produced:

- `10-3-2 -> 9` (standard arithmetic: `5`)
- `8/4/2 -> 4.0` (standard arithmetic: `1.0`)
- `1+-2 -> IndexError`
- `1/-2 -> IndexError`

The task promises `+ - * /`, correct arithmetic precedence, and unary minus. The ten hidden tests omit chained subtraction/division and these unary forms. Thus the report's 68/120 is arithmetically faithful to the DB but at least one pass too high against the written contract. Removing this one demonstrated false positive would produce 67/120 = 55.83%, Wilson 95% `[0.4690, 0.6440]`; this audit does **not** alter the stored result.

### P1-1 — Redirect reference and hidden suite violate the security contract

`validate-redirect-url` says dangerous schemes such as `javascript:` and `data:` must be rejected. The reference returns all of these unchanged when the netloc equals the allowed host:

- `javascript://app.example.com/x`
- `data://app.example.com/x`
- `ftp://app.example.com/x`

The hidden tests cover only dangerous scheme strings without a netloc. `validate_task` passes because it validates the reference against the tests, not the tests/reference against the description. Seven current model passes on this task cannot be certified against the full written security contract.

### P1-2 — Hidden/reference material is not protected from an arbitrary agent

`run_once` passes the full `Task` object to `agent.act`. That object contains absolute `task_dir`, `reference_dir`, and suite metadata. The agent workspace omits hidden tests, but an in-process agent can read them directly from the host or simply copy the reference solution. During grading, submitted source also executes in the same clean room where `test_hidden.py` is materialized and can inspect it at runtime. The existing tests prove workspace separation, not secrecy from hostile code.

### P1-3 — No security or dependency isolation; host state changes grading

`LocalSandbox` explicitly is not security isolation. Agent code and graded code have host filesystem/process/network access. The grader uses the current interpreter environment rather than a pinned task image. Evidence: qwen toposort run 4 imported undeclared `networkx`; it executed because NetworkX 3.4.2 is installed locally. Another machine can grade the same patch differently.

### P1-4 — 75 published rows evaluate obsolete task versions

`async-batched`, `refactor-order-validation`, and `top-k-frequent` are current v1.0.1, while all 25 real-model rows per task remain v1.0.0: 75/600 rows total. The report and README disclose the fork, which prevents deception, but the headline is not a result on the current task pack.

### P1-5 — Real-run reproduction metadata is insufficient

Only qwen-7B and llama digests are documented. The DB stores no model digest, Ollama version, temperature, seed, prompt/transcript, command log, host image, or dependency snapshot per run. `eval_persist.py` resets `OllamaAgent._call` on restart; resumed jobs therefore reuse `base_seed + call_index` from 42 rather than preserving a deterministic task/run-to-seed mapping. Exact generations cannot be reproduced or even reconstructed.

### P1-6 — The executable leaderboard is micro-pooled despite the framework's macro-domain requirement

`runner/afa_runner/report.py::leaderboard` counts all valid runs equally over 24 tasks. The framework explicitly says macro-domain aggregation is required to prevent task-bank composition from making the overall score “a backend score wearing an overall costume.” Backend touches 17/24 tasks. The current ordering happens to remain plausible, but the published headline does not implement the framework's documented overall aggregation rule.

### P1-7 — Timeout/infra gates do not behave as documented end to end

The framework says agent timeouts are SIGKILLed and grader-side timeouts are `INFRA_FAILURE`. In code, `run_once` measures an in-process `agent.act` only after it returns; a hung agent can hang the harness. `ScriptAgent` does not propagate `CommandResult.timed_out` as `RunStatus.TIMEOUT`. Pytest/grader timeouts become errored suites under a still-`VALID` record and are counted as losses. Only adapter-declared transport failures (notably Ollama connection errors) are reliably voided.

## Major findings

- **P2-1 — Forensic raw layer is incomplete.** Runs 1–500 have no patch or per-test rows; 501–600 have 100 patches and test rows on 99 runs. No run stores transcript text. Required deepseek/qwen3/gemma patch-level diagnoses are therefore impossible.
- **P2-2 — Real evaluation is an adapter benchmark.** `OllamaAgent` is a single-shot fenced-code rewriter that never runs visible tests. A response in an unsupported format becomes a no-edit failure. Parser failures are not separately tracked. Claims must be limited to this exact prompt/parser, not general model or coding-agent ability.
- **P2-3 — Report failure categories are inaccurate.** The HTML calls every changed non-pass a “wrong-fix” and defines it as hidden-test failure. This lumps regression/gate/collection failures together. For qwen-7B, 3 of 52 such failures have `G=0`; across the five models there are 110 changed gate failures.
- **P2-4 — `Q=1.0` means unmeasured, not perfect.** All 600 rows have Q=1 because quality inputs are absent. The framework describes a pinned ruff/mypy/bandit/parsimony toolchain, but the runner does not execute it. The report displays mean Q=1.000 without labeling it unavailable.
- **P2-5 — Deterministic evidence policy is not implemented.** The framework says a hash-verified deterministic cell contributes once and gets a degenerate interval. Code detects determinism but the leaderboard still counts all repetitions; synthetic oracle/noop receive binomial Wilson intervals over 120 generated rows.
- **P2-6 — No uniqueness constraint on run identity.** SQLite permits duplicate `(agent, task_id, task_version, idx)` rows. Current DB has zero duplicates, but concurrent/resumed writers can inflate n. `load_runs` also does not select a formula version, so future multi-version score rows would duplicate runs in aggregation.
- **P2-7 — Backend-heavy, overlapping domain evidence.** Backend touches 17 tasks and 85 runs/model, while other domains have five tasks/25 runs. API/performance have only three primary tasks and n_eff 22.86. A single task contributes to multiple domain claims.
- **P2-8 — Task difficulty and discriminative behavior are uneven.** `query-builder` is a simple fluent class labeled d4 yet qwen-7B is 0/5; this looks more like adapter/output failure than code difficulty. `top-k-frequent` is a memorized `Counter` idiom labeled d4 and gemma is 4/5. `toposort` is 0/25 and needs a stronger-model anchor before it can be called well-calibrated.
- **P2-9 — Visible tests are often deliberately weak and unused by the real adapter.** Many tasks expose one or two tests; redirect's visible tests pass the buggy snapshot. This measures one-shot prompt completion more than iterative coding-agent behavior.
- **P2-10 — Performance gating is host-dependent.** 20-second whole-suite timeouts reject quadratic code on this machine, but no CPU/memory image is pinned and no per-test performance budget is persisted.
- **P2-11 — Rank ranges are a documented heuristic, not statistical rank confidence intervals.** The rule `LCB_a > p_hat_b` is one-sided, ignores b's uncertainty, and has no family-wise correction. The framework admits this; the report should not imply mathematically proven ties.
- **P2-12 — SQLite resource leaks are visible in the suite.** Seven `ResourceWarning`s for unclosed SQLite connections appeared during the full run. The warning attribution occurs at garbage collection, so the exact originating tests are not proved by the warning location.
- **P2-13 — Product surface is absent.** No FastAPI, Next.js, dashboard, run detail viewer, formal CLI entry point, or contributor guide exists.

## Minor findings

- **P3-1:** the literal requested command `python -m pytest` fails because `python` is absent; the documented `python3 -m pytest` works.
- **P3-2:** the pre-existing untracked audit artifacts were stale before this audit. They have since been replaced by the current audit set and grouped under `codex-audit/`; the historical HTML is retained there as an explicitly named legacy artifact.
- **P3-3:** report intervals in task/domain cells rely on hover `title` text, which is weak for keyboard/touch accessibility and non-expert reading.
- **P3-4:** `editable_paths` are package-wide (`pkg/**`) rather than target-file-specific, allowing unnecessary sibling edits; regression tests catch only covered behavior.
- **P3-5:** task/domain weights are assumed non-negative and valid but are not schema-validated by `load_task`/kernel functions.

## Repository state audit

| Check | Evidence-backed result |
|---|---|
| Git status | No tracked modifications before audit; four pre-existing untracked audit artifacts. After audit, requested audit artifacts remain untracked. |
| HEAD | `798a5b3` — “Backfill audit-trail (Phase 30) and complete P2-1 doc reconciliation” |
| Recent commits | `4505bad` P2/P3 closure; `f70eb6d` P0 data-integrity repair; `036cde4` failure inspection. |
| Origin sync | PASS — after fetch, `HEAD...origin/master = 0 0`. GitHub default branch is `master`; repository visibility is PRIVATE. |
| Generated artifacts | Intentional: `reports/*` is ignored except tracked `reports/runs.sqlite` and `reports/leaderboard.html`. DB/HTML exactly match HEAD hashes. |
| SQLite integrity | PASS — `PRAGMA integrity_check=ok`, foreign-key check empty, 600 unique run identities, zero reconstructed hashes, zero synthetic model rows. |
| Report reproducibility | PASS — SHA-256 before rebuild, after rebuild, and HEAD all `87ca6c…574`; DB SHA-256 `519bee…663`. |
| README/DB headline | PASS — five real models × 120 rows; pass totals and names match. |
| README/current task pack | PARTIAL — honestly discloses three v1.0.1 tasks were not reevaluated. |
| DEVLOG/current git | PASS — current branch/push state and untracked audit files agree. Historical states are labeled historical. |
| Framework/executable behavior | FAIL — macro ranking, timeout taxonomy, hidden-test secrecy, deterministic counting, and quality toolchain differ from the executable harness. |

No missing local commit or unpushed `master` change was found. No current DEVLOG statement falsely calls committed project code uncommitted.

## Test suite audit

### Execution result

| Metric | Result |
|---|---:|
| Literal `python -m pytest` | FAIL before collection: `python: command not found` |
| Actual documented command | `python3 -m pytest -ra --durations=20 -W default` |
| Collected | **366** |
| Passed | **366** |
| Failed | **0** |
| Skipped | **0** |
| Warnings | **7** (`ResourceWarning`: unclosed SQLite connections) |
| Runtime | **147.69 s** |

No flaky failure was observed. Suspicious/time-sensitive coverage includes 50 ms asyncio timeouts, a process-group kill test that consumes ~13 s, and task performance suites enforced by 20 s whole-suite timeouts. Margins passed on this host but are not container-calibrated.

### Meaningfulness

| Required area | Verdict | Evidence |
|---|---|---|
| Core score formula/gates | PASS | Direct unit anchors, degenerate suites, Q edge cases. |
| Wilson intervals | PASS | Independent reference calculations, endpoint leak regression, broad edges. |
| Domain scores | PASS | Weighted pooling, Kish n_eff, threshold and zero-contribution cases. |
| Ranking tie ranges | PASS for implemented heuristic | Independent rank calculations and self-comparison regression. |
| Clean-room protections | PASS for path layer | conftest/sitecustomize/usercustomize/pytest config/`*.pth`, case variants, symlinks, allow-list. |
| Hidden tests outside agent workspace | PASS | End-to-end workspace probe. |
| Hidden/reference inaccessible to arbitrary agent | **FAIL / untested** | Full `Task` path object is handed to agent. |
| Infra failures voided | PASS for explicit `infra_failed` | Kernel/pipeline/Ollama tests. Grader/script timeout taxonomy is not covered end to end. |
| Report correctness | PASS/partial | Exact Wilson/rank/domain values tested; no test proves failure taxonomy labels are semantically correct. |
| Production DB/report path | PASS | Combined-report integration test and byte-identical rebuild. |

**Test quality score: 8.5/10.** The suite is not superficial. It is strongest around pure math and path-based clean-room defenses; it is weakest where host isolation, task-contract completeness, run provenance, and external process lifecycle matter.

## Task pack audit

All 24 manifest entries have `task.json`, snapshot, reference overlay, visible tests, hidden tests, and regression tests. All use package-scoped editable allow-lists and protected test globs. The full suite's 24 parametrized `validate_task` cases confirm, for every **current** task version: reference scores 1.0 identically three times; the snapshot passes regression, fails full hidden, and scores zero due to empty diff.

That validator proves test/reference consistency. It does **not** prove that tests/reference implement the natural-language contract, as the redirect and expression counterexamples demonstrate.

| task_id | d | domains | validation | risk | quality /10 | notes |
|---|---:|---|---|---|---:|---|
| escape-html | 2 | security, backend | PASS | low | 7.5 | Clear and well covered; toy escaping rather than broad security. |
| fix-binary-search | 2 | backend | PASS | medium | 8.0 | Good edge suite; snapshot already passes 3/9, so partial S has a known baseline channel. |
| fix-list-dedup | 2 | backend | PASS | medium | 6.5 | Clear order behavior, but “items” hashability is unspecified while reference requires hashable elements. |
| async-retry | 3 | async, backend | PASS | medium | 7.5 | Retry count/last exception covered; only one visible test and integer type edge is thin. |
| async-timeout | 3 | async | PASS | medium | 7.5 | Cancellation tested with generous margins; timing remains environment-sensitive. |
| fix-roman-numerals | 3 | backend | PASS | low | 7.5 | Good subtractive coverage; intentionally does not define Roman validation/canonicality. |
| implement-lru-cache | 3 | backend, api | PASS | medium | 7.0 | Core recency behavior covered; capacity zero/negative contract is absent. |
| mask-secrets | 3 | security | PASS | medium | 6.5 | Regex contract is partly ambiguous (bearer/email grammar) and hidden suite is narrow. |
| merge-intervals | 3 | backend, performance | PASS | low | 8.0 | Strong behavioral suite; performance secondary tag has no strict complexity discriminator. |
| paginator | 3 | api | PASS | medium | 7.5 | Precise API; invalid constructor inputs/per-page zero are unspecified. |
| result-type | 3 | api, backend | PASS | low | 8.0 | Exact, coherent API and useful map no-call test. |
| sanitize-filename | 3 | security, backend | PASS | medium | 7.5 | Good stated component checks; not a general cross-platform filename security policy. |
| async-batched | 4 | async, performance | PASS v1.0.1 | high (evaluation) | 8.5 | Current suite is strong; every published model row is stale v1.0.0. |
| async-first-success | 4 | async | PASS | medium | 8.0 | Cancellation and input-order final exception are explicit and tested. |
| async-gather-bounded | 4 | async, backend | PASS | medium | 6.5 | Bound/order/exception covered; invalid limit and cancellation cleanup are not. |
| fix-path-traversal | 4 | security, backend | PASS | medium | 7.0 | Solid POSIX containment core; base-root and broader filesystem semantics are thin. |
| grid-paths | 4 | performance | PASS | medium | 8.0 | Large discriminator is useful; difficulty is closer to 3 for a standard DP/binomial task. |
| query-builder | 4 | api, backend | PASS | high | 6.0 | Written task is simple; 1/25 result suggests adapter/output weakness. Difficulty 4 is implausible. |
| refactor-order-validation | 4 | backend, api | PASS v1.0.1 | high (evaluation) | 8.5 | Current helper/delegation suite is strong; all published rows use weaker v1.0.0. |
| top-k-frequent | 4 | performance, backend | PASS v1.0.1 | high (evaluation) | 8.5 | Current suite has strong complexity/identity probes; published gemma outlier is on v1.0.0. Idiom makes d4 debatable. |
| toposort | 4 | backend | PASS | medium-high | 8.5 | Clear compound contract and 12 tests; 0/25 needs a stronger-agent anchor, not immediate relaxation. |
| two-sum-indices | 4 | performance, backend | PASS | low-medium | 8.0 | Good correctness and 300k scale tests; canonical idiom makes d4 slightly high. |
| validate-redirect-url | 4 | security | PASS tests, **FAIL contract** | **critical** | 4.5 | Reference accepts hosted javascript/data schemes contrary to description. |
| expression-evaluator | 5 | backend | PASS tests, **FAIL coverage** | **critical** | 5.0 | Hidden suite awards a nonconforming qwen parser; no enforcement of “do not use eval.” |

Mean task quality: **7.3/10**. The pack is useful but not yet a gold-standard benchmark. Current `validate_task` status must not be presented as proof of semantic fairness.

## Scoring/math audit

### Verified correct

- `S = G * T_hidden * (0.85 + 0.15Q)` is implemented exactly.
- `T_hidden` uses hidden-test weights, returns zero for no hidden tests or nonpositive total weight, and is clamped.
- Functional pass requires all gates, nonempty hidden tests, every hidden test passed, and positive hidden weight; the all-zero-weight leak is fixed.
- Explicit `INFRA_FAILURE` rows are voided and excluded from n.
- Wilson arithmetic matches an independent implementation to full displayed precision.
- Stability and unbiased pass@k are correctly implemented per cell.
- Domain pass pooling and Kish effective-N formulas match the documentation.
- Current ranks are not affected by float residue; all-fail LCB is exactly zero and self-comparison is excluded.

### Reliability limitations

- The ranking “tie” ranges are heuristic pairwise ranges, not simultaneous confidence intervals.
- Wilson pooling treats repeated, heterogeneous task runs as exchangeable Bernoulli trials. The framework itself admits within-task correlation and between-task overdispersion make bands optimistic.
- Quality is not measured in the published evaluation; all Q values default to one.
- Baseline-equivalent partial hidden credit remains active in formula v0.1; `baseline_adjusted_t_hidden` exists but is not wired.
- Overall leaderboard uses micro-pooled runs, not the documented macro-domain score.
- Deterministic cell evidence is detected but not de-duplicated.
- No epsilon policy exists for rank comparisons at exact float boundaries; current values are not near a problematic boundary.

### Independent manual recomputation

| agent | c/n | p_hat | Wilson 95% interval | LCB | report match |
|---|---:|---:|---:|---:|---|
| qwen2.5-coder:7b | 68/120 | 0.566667 | [0.477298, 0.651900] | 0.477298 | PASS |
| deepseek-coder:6.7b | 38/120 | 0.316667 | [0.240227, 0.404480] | 0.240227 | PASS |
| llama3.2:latest | 26/120 | 0.216667 | [0.152366, 0.298545] | 0.152366 | PASS |
| oracle synthetic baseline | 120/120 | 1.000000 | [0.968980, 1.000000] | 0.968980 | PASS calculation; interval concept is questionable for a deterministic synthetic row |
| noop synthetic baseline | 0/120 | 0.000000 | [0.000000, 0.031020] | 0.000000 | PASS calculation; same caveat |

**Scoring/math reliability score: 7.5/10.** Arithmetic correctness is high. Specification conformance and inferential interpretation are not.

## Evidence-backed model results

All current DB rows have status `valid`; there are no stored timeouts, agent errors, or infra voids. “Hidden miss” below means changed code with `G=1` but no functional pass. “Changed gate fail” means changed code with `G=0`; the DB does not identify which gate failed for legacy rows.

| rank | model | total | valid | pass | fail | void | no-edit | hidden miss | changed gate fail | rate | Wilson 95% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | oracle (synthetic) | 120 | 120 | 120 | 0 | 0 | 0 | 0 | 0 | 100.0% | [96.9%, 100%] |
| 2 | qwen2.5-coder:7b | 120 | 120 | 68 | 52 | 0 | 0 | 49 | 3 | 56.7% | [47.7%, 65.2%] |
| 3–4 | deepseek-coder:6.7b | 120 | 120 | 38 | 82 | 0 | 16 | 41 | 25 | 31.7% | [24.0%, 40.4%] |
| 3–5 | qwen2.5-coder:3b | 120 | 120 | 32 | 88 | 0 | 47 | 33 | 8 | 26.7% | [19.6%, 35.2%] |
| 4–5 | llama3.2:latest | 120 | 120 | 26 | 94 | 0 | 21 | 48 | 25 | 21.7% | [15.2%, 29.9%] |
| 6 | gemma2:2b | 120 | 120 | 6 | 114 | 0 | 12 | 53 | 49 | 5.0% | [2.3%, 10.5%] |
| 7 | noop (synthetic) | 120 | 120 | 0 | 120 | 0 | 120 | 0 | 0 | 0.0% | [0.0%, 3.1%] |

Parser failures and grader timeouts are **UNVERIFIED/untrackable** in the committed rows: no explicit parser status exists, transcript text is absent, and grader timeout notes are not persisted. “No-edit” is a symptom, not a diagnosis.

### Strength and failure diagnosis by model

- **qwen2.5-coder:7b:** strongest domains security (76%) and API design (70%); weakest async (20%). Eight tasks are 5/5. It always edited, so its failures are mostly real code/test misses. However its only expression pass is contract-invalid, and the async/query cells show substantial capability gaps.
- **deepseek-coder:6.7b:** strongest security (52%) and performance (45%); weakest async (24%) and API (25%). Perfect on `result-type` and `two-sum-indices`; zero on ten tasks. Sixteen no-edits plus 25 changed gate failures show output/gating weakness in addition to wrong algorithms.
- **qwen2.5-coder:3b:** strongest security (40%) and backend (32.8%); zero on async. Forty-seven no-edits are the dominant failure signal, but whether this is refusal, malformed fenced output, or parser mismatch is unknowable.
- **llama3.2:latest:** strongest performance (50%); weakest async (4%) and API (12.5%). Strong on merge/top-k/two-sum; 21 no-edits and 25 changed gate failures show format/regression fragility.
- **gemma2:2b:** performance 20% is almost entirely the top-k outlier; API/async/security are 0%. It edits often but usually fails gates or hidden tests. Calling it simply “bad” hides the memorized-idiom behavior.

## Representative failure forensics

| model | task/run | what changed | failed tests | root cause/classification | evidence |
|---|---|---|---|---|---|
| qwen-7B | expression idx0 | Added a stack evaluator but tokenized with `expr.replace(' ', '').split()`, producing one token for normal compact expressions. | All 10 hidden tests | Model implementation failure; task prompt is clear. | DB id 546, persisted patch, G=1/T=0, named failed tests. |
| qwen-7B | toposort idx4 | Imported NetworkX and treated dependency edges in the wrong direction. | 6/12 hidden: chain, diamond, disconnected, implicit node, lexicographic tests | Model semantic failure **plus harness host-dependency flaw**. | DB id 545, persisted patch/test rows; NetworkX 3.4.2 present. |
| llama3.2 | fix-path-traversal idx4 | Rejected any joined string containing `..`; used an ineffective absolute-path condition. | absolute component; safe internal `reports/../public` | Model failure. | DB id 585, G=1, T=5/7, patch and failed names. |
| llama3.2 | toposort idx2 | Kahn-like code increments indegree of dependencies and traverses dependency lists as outgoing edges; omits implicit nodes. | 7/12 hidden | Model semantic failure. | DB id 593, G=1, T=5/12, patch and failed names. |
| deepseek | fix-binary-search idx0 | Exact patch **UNVERIFIED**; stored structure says one file, +3/-3. | Exact tests **UNVERIFIED**; G=0, T=0. | Changed gate failure; exact model/parser/regression cause is unrecoverable. | DB id 111; patch/test/transcript absent. |
| deepseek | toposort idx0 | Exact patch **UNVERIFIED**; +35/-6. | Exact tests **UNVERIFIED**; only 1/12 hidden passed with G=1. | Genuine hidden-test miss, likely model algorithm failure; exact defect unverified. | DB id 146. |
| qwen-3B | fix-binary-search idx0 | No file changed. | Snapshot baseline passes 3/9 hidden, but diff gate zeros score. | No-edit; parser failure vs model response failure **UNVERIFIED**. | DB id 61: files=0, G=0, T=1/3. |
| gemma2 | top-k idx0 | Exact code **UNVERIFIED**; one file +10/-1. | None under stored v1.0.0 suite (G=1/T=1). | Legitimate under old tests, but patch absent and current task is v1.0.1; source-level claim remains unverified. | DB id 206; `docs/FAILURE_INSPECTION.md` explicitly says inference, not patch read. |

`toposort` is the only literal 0/25 task. `expression-evaluator` is 1/25 in SQLite, but the single pass is demonstrably nonconforming, so it is effectively 0/25 against its written contract. The old failure-inspection document's “expression 0/5” describes an earlier 15-run slice, not the final 25-run matrix.

## Domain scoring audit

Composition and evidence mass:

| domain | tagged tasks | primary tasks | raw runs/model | n_eff | threshold |
|---|---:|---:|---:|---:|---|
| api-design | 5 | 3 | 25 | 22.86 | met (barely) |
| async-concurrency | 5 | 5 | 25 | 25.00 | met (barely) |
| backend | 17 | 8 | 85 | 76.22 | met/dominant |
| performance | 5 | 3 | 25 | 22.86 | met (barely) |
| security | 5 | 5 | 25 | 25.00 | met (barely) |

| model | api-design | async-concurrency | backend | performance | security |
|---|---|---|---|---|---|
| qwen-7B | 70% [49.5,84.7] | 20% [8.9,39.1] | 60.8% [49.6,71.0] | 50% [31.0,69.0] | 76% [56.6,88.5] |
| qwen-3B | 30% [15.3,50.5] | 0% [0,13.3] | 32.8% [23.3,43.9] | 22.5% [10.1,42.8] | 40% [23.4,59.3] |
| deepseek | 25% [11.8,45.4] | 24% [11.5,43.4] | 27.2% [18.5,38.1] | 45% [26.8,64.6] | 52% [33.5,70.0] |
| llama3.2 | 12.5% [4.2,31.6] | 4% [0.7,19.5] | 24% [15.8,34.7] | 50% [31.0,69.0] | 24% [11.5,43.4] |
| gemma2 | 0% [0,14.4] | 0% [0,13.3] | 6.4% [2.7,14.2] | 20% [8.5,40.1] | 0% [0,13.3] |

The report's displayed rates and tooltip intervals match these values. Interpretation remains weak: API/performance intervals use effective n below the nominal 25-run threshold; backend dominates the overall micro leaderboard; security includes a contract-broken redirect task; gemma's performance score is driven by one top-k cell; and each overlapping task is reused across domain claims.

**Domain coverage score: 6.0/10.** “Displayable” is not the same as “well covered.”

## Suspicious results requiring inspection

1. **qwen-7B / expression 1/5:** confirmed false-positive hidden coverage; mandatory fix and rerun.
2. **all models / redirect:** task/reference contract mismatch means the seven passes are not fully certified.
3. **gemma / top-k 4/5:** credible against v1.0.0 but patch evidence is absent and current v1.0.1 adds adversarial probes.
4. **qwen-7B / query-builder 0/5:** implausible for a trivial fluent class; likely adapter/output/gate effects, but the legacy artifacts are missing.
5. **deepseek / binary-search 0/5:** surprisingly poor on d2; four changed gate failures and one no-edit, but patches are missing.
6. **toposort 0/25:** clear, reference-valid hard anchor, yet no real pass means calibration above small local models is unknown.
7. **async-batched 1/25:** all results are on the weaker v1.0.0 suite; current discrimination is unmeasured.
8. **qwen-3B 47 no-edits:** likely strong prompt/parser interaction; cannot be attributed solely to coding ability.

## Mistakes and downtimes

Exact wall-clock timestamps for early uncommitted phases were not persisted; phase ordering below is the most precise verifiable timeline. Commit dates exist only for committed milestones.

| phase | issue | cause | impact | fix | evidence | remaining risk |
|---|---|---|---|---|---|---|
| Framework pre-build | impossible pass@k example, inconsistent point-biserial, Q divide-by-zero | design/numeric errors | Could have corrupted formulas; caught before executable release | corrected during verification | DEVLOG phases 0/5 | Framework remains partly aspirational. |
| Phase 5 | Wilson all-fail float leak | sub-epsilon `centre-half` residue | Zero-pass LCB could be `1.39e-17`; contributed to impossible ranks | exact endpoint snapping | confidence code/tests, DEVLOG bug 3 | No current impact. |
| Phase 5 | ranking self-comparison | agent included in its own out-ranking sets | ~7,500 impossible ranges in 500k sweep | exclude self | ranking code/test, DEVLOG bug 4 | Heuristic itself remains nonstandard. |
| Phase 5 | all-zero hidden weight | `all([]/zero)` path allowed X while S=0 | Possible false functional pass | require nonempty hidden and `T_hidden>0` | scoring code/tests | Task loader still does not validate positive weights. |
| Phase 6 | conftest/sitecustomize/`*.pth` injection | clean room applied arbitrary agent files | Agent could monkeypatch tests and score 1 without fixing | always-protected paths + editable allow-list; later casefold/symlink hardening | diffing/e2e tests, DEVLOG bug 6/12/13 | Target source still executes with host privileges and can read hidden tests. |
| Phase 10 | Ollama `# FILE:` parser bug | model put marker inside code fence | Valid responses produced unusable/no edits | parse in-block marker | adapter code/tests, DEVLOG bug 7 | Other response formats still become unclassified no-edits. |
| Phase 13 | stale `.pyc` UnicodeDecodeError | reference reader treated bytecode as text | First eval attempt crashed; no usable score | skip/strip bytecode and caches | DEVLOG phase 13; grader/diff code | Host/environment still unpinned. |
| Phase 14 | Ollama connection refused scored as model loss | transport error mapped to `AGENT_ERROR` | Diagnosis runs were contaminated; initial belief that Phase-13 scores were contaminated was later disproved by clean rerun | `infra_failed -> INFRA_FAILURE`, checked before errored | DEVLOG phases 14/24; adapter tests | Only adapter-declared infra is voided; grader infra remains scored. |
| Phases 15/18/19 | Ollama/background service died or was unreachable | job lifecycle reaped background processes; not OOM | Clean rerun killed; diagnosis interrupted; no final score contamination | bundle serve+eval, readiness wait | DEVLOG phases 15–19 | Operational recipe not automated in main quickstart. |
| Phase 26 | long model jobs killed/reaped | tooling turn/job lifetime | Repeated lost progress; potential partial matrices | per-run SQLite persistence and resume | `eval_persist.py`, DEVLOG phase 26 | Resume resets seed call counter; DB lacks unique identity. |
| Phase 27–30 | report gap-filled missing model cells and DB ignored | `KNOWN_OLD` reconstructed earlier real results without committed raw rows | P0 reporting/reproducibility failure; original audit scored 53/100 | completed 600 real runs, removed gap fill, tracked DB/HTML, labeled synthetic baselines | commits `f70eb6d`, DB/hash tests | First 500 artifacts remain irrecoverable. |
| Phase 27 | stale/incorrect model label (`llama3.2:3b`) | documentation label drift | Misidentified evaluated model | corrected to `llama3.2:latest` | README/DB | Three other run-time digests still undocumented. |
| Phase 33–34 | parsimony documentation only partially reconciled | formula block fixed before examples/prose | temporary spec contradiction | Phase 34 completed examples/prose | commit `798a5b3` | Larger framework/runtime drift remains. |
| Current audit | SQLite ResourceWarnings | unclosed connection objects collected during suite | No observed score contamination; hygiene/flakiness risk | **not fixed (audit-only)** | full pytest warning summary | open. |

## Report audit

The static report is **detailed enough for a high-level internal comparison**, understandable to a technically literate new user, and numerically accurate relative to SQLite. It is **not** detailed or semantically precise enough for forensic evaluation claims.

### Present and working

- leaderboard, pass rates, Wilson intervals, LCB explanation, rank ranges
- per-task heatmap with difficulty and task-version badges
- per-agent summaries, mean S/Q, no-edit/changed-failure/void counts
- domain profile with thresholds, weights, intervals in tooltips
- explicit five-real-model provenance and synthetic oracle/noop labels
- persisted run window and artifact coverage
- honest current/stored task-version mismatch warning

### Defective or missing

- “wrong-fix” mislabels every changed failure, including gate failures
- no raw-run drilldown, diff viewer, transcript/prompt viewer, or command log
- no hidden-test failure output/trace summary (only names exist for 99 runs)
- no parser diagnostics or distinct malformed-output category
- no reliable timeout diagnostics
- no runtime distribution, token, energy, or cost data
- no per-run timestamp/config view
- no downloadable CSV/JSON; SQLite is available but not a user-facing export
- no reproducibility manifest or environment/model digest block
- no interactivity/filtering/dashboard
- no accessible always-visible domain/task intervals; many details are hover-only
- no explanation that Q=1 means unavailable evidence
- no warning that “95%” assumes correlated heterogeneous runs are binomial/exchangeable

Pixel-level visual rendering was not independently verified in this audit because the local-file browser target was blocked by the audit environment; HTML structure, content, CSS, regenerated bytes, and renderer tests were inspected. Mark visual polish beyond source-level evidence **UNVERIFIED**.

**Report quality score: 7.0/10.** Good static overview; inadequate forensic surface.

## Security and anti-gaming audit

| Control | Verdict |
|---|---|
| protected paths / editable allow-list | PASS; broad package-level allow-list could be narrower |
| hidden tests absent from model workspace | PASS for built-in adapter |
| hidden/reference unavailable to arbitrary agent | FAIL |
| clean-room diff-only grading | PASS structurally |
| conftest/sitecustomize/usercustomize/pytest config/`*.pth` injection | PASS at path layer, including case variants |
| symlink/out-of-tree diff capture | PASS (symlinks ignored) |
| model parser path traversal | PASS for `../` resolution guard |
| edits to visible/hidden tests | PASS scope gate; hidden tests are never in agent workspace |
| generated/cache artifacts | PASS for declared ignored dirs/bytecode; other binary files are silently omitted |
| host process/filesystem/network isolation | FAIL |
| pinned grader dependencies/resources | FAIL |
| runtime introspection of hidden tests by submitted code | FAIL |

Docker or an equivalent sandbox would provide a read-only base image, workspace-only agent mount, hidden/reference exclusion, network denial, CPU/memory/PID limits, deterministic dependencies, and killable process boundaries. The grader must be a separate image/process and should avoid exposing readable hidden source to submitted code where practical. Docker alone does not automatically solve runtime hidden-test introspection if tests and submitted code share a readable filesystem.

**Security/anti-gaming score: 5.0/10.** Strong trusted-path defenses; not safe against hostile agents or hostile submitted code.

## Reproducibility checklist

| item | result | evidence/defect |
|---|---|---|
| README test quickstart | PASS | `python3 -m pytest` -> 366 passed |
| deterministic demo | PASS | `run_demo.py` produced expected 5/5, 3/5, 0/5 table |
| dependencies documented | PARTIAL | pytest/Ollama stated; no lockfile/image; host packages affect grading |
| Python version | PASS | tested 3.13.2; project requires >=3.10 |
| model server requirement | PASS | Ollama documented; local version 0.17.4 verified |
| all model names/tags | PASS | five DB agents match README/report |
| exact model digests | FAIL | only qwen-7B/llama documented; current local other digests do not prove run-time digests |
| run command and n | PASS | `eval_persist.py <model> 5`; 5 × 24 verified |
| DB location | PASS | tracked `reports/runs.sqlite` |
| report command | PASS | rebuild byte-identical |
| deterministic manifest | PASS as committed artifact | 24 unique entries; no orphan dirs; no formal schema/generator |
| generated files ignored intentionally | PASS | report exceptions explicit in `.gitignore` |
| temperature/base seed | PARTIAL | 0.8/42 documented; actual per-run seed mapping not stored and changes on resume |
| resumability | PARTIAL | version-aware skip works; no DB uniqueness/race guard and seed schedule is not replayable |
| infra failures separated | PARTIAL | explicit adapter infra voided; grader/script infra taxonomy incomplete |
| full patch/test artifacts | FAIL | only 100/600 patches, 99/600 test-result coverage |
| transcripts/prompts/commands | FAIL | only transcript+patch hash stored |
| run timestamps | PARTIAL | DB timestamps and aggregate window exist; no per-run report view/config linkage |
| current task versions evaluated | FAIL | 75 rows across three tasks are v1.0.0 vs current v1.0.1 |
| environment/repro manifest | FAIL | no OS/hardware/dependency/model/config manifest |

**Reproducibility score: 6.5/10.** The published aggregate is reproducible from committed evidence; the underlying generations are not reproducible.

## Product readiness audit

README is clear about the repository layout, current numbers, baselines, version fork, and major roadmap omissions. DEVLOG is unusually thorough. The actual UX remains a collection of Python example scripts with positional arguments and no unified `afa` CLI/help/config workflow. There is no dashboard, frontend, API, run-detail viewer, task/agent author guide, or contribution process.

This is resume-presentable today as a **research/engineering project** if described honestly: “built and audited a deterministic local evaluation kernel and 24-task experiment harness.” It is not resume-presentable as a product-ready benchmarking platform or secure autonomous-agent arena.

**Product readiness score: 4.5/10.**

## What to do next

### 1. Mandatory

1. Quarantine/fix `expression-evaluator` and `validate-redirect-url`; add contract-derived adversarial tests; rerun all model cells that touched them.
2. Define and implement the executable scoring contract: macro vs micro leaderboard, timeout/infra taxonomy, deterministic-run evidence, Q unavailable semantics, and baseline-adjusted continuous score. Version the formula/report.
3. Isolate agent and grader in pinned, network-disabled processes/containers. Pass agents a sanitized task view with no host reference/hidden paths.
4. Rerun all five models on current task versions with complete per-run artifacts/configuration and a stable seed derived from `(evaluation_id, model_digest, task_version, idx)`.

### 2. Should do

1. Add DB uniqueness constraints, formula-version selection, migrations, and a run/evaluation configuration table.
2. Persist transcript/prompt, parser outcome, stdout/stderr, gate-by-gate results, grader timeout cause, token/runtime stats, and model/server digests.
3. Add stronger visible tests and an iterative test-running real-agent adapter; label single-shot results separately.
4. Add primary API/performance tasks and stronger-model anchors; do not add more backend tasks first.
5. Correct report failure taxonomy and expose raw run/diff/test/transcript drilldown plus JSON/CSV export.

### 3. Optional

1. Build FastAPI/Next.js only after the raw schema and semantics are stable.
2. Add hierarchical difficulty/overdispersion models once the agent roster and task bank justify them.
3. Add Docker alternatives for macOS/Linux portability and calibrated performance tiers.

### 4. Do not do yet

- Do not add more models to the current contaminated/stale matrix.
- Do not market Wilson rank ranges as statistically proven ties.
- Do not build a glossy dashboard over missing forensic data.
- Do not claim untrusted-agent safety, universal model ability, or a fair current-pack leaderboard.

## Final verdict

AgentForge Arena is not vaporware. The kernel works, the committed DB really contains 600 model runs, the report really regenerates byte-for-byte, and the tests are mostly serious. But “the math is right” is not enough. The task oracle is wrong in one security task, another hidden suite awards a demonstrably wrong parser, the headline aggregation diverges from the framework, and the isolation/provenance boundary is too weak for adversarial agents.

The honest label is: **a promising, well-tested research harness with a reproducible aggregate artifact, not yet a reliable benchmark standard.**
