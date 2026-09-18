# AgentForge Benchmark — Version-Impact / Remediation Manifest

**Schema version**: `1.0.0`  
**Generated at commit**: `36650d7bb6705d482819b91320c5a3c4b579e679`  
**Source commits**: e2e4513 (17-task remediation), 36650d7 (4-task follow-up fixes)  
**Mission**: ORACLE Mission 2 -- Benchmark Remediation & Coverage Hardening

## Summary

- **18 tasks** had grading-relevant hidden-suite changes (version bumped)
- **540 historical runs** (6 models x 5 reps x 18 tasks) are no longer directly comparable to the new task versions
- **51 model/task cells** previously scored a functional PASS and are the highest-priority re-evaluation targets (a strengthened oracle is most likely to change these)

## Per-task detail

### `async-first-success`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: Generic AST mutant survivors (3/21 relevant in the prior full run) at afirst/first.py, including a remove_branch/remove_validation pair and a drop_exception_handling survivor.

**Change**: Added targeted semantic hidden tests discriminating the underlying untested edge cases.

**Historical comparability**: Old runs remain valid evidence for async-first-success v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for async-first-success (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  No model previously passed this task — re-evaluation still required for a current claim, but no stored score is at risk of flipping from pass to fail.

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 0 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (none previously passed) since those are the scores most likely to change under the strengthened oracle.

---

### `async-gather-bounded`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: Generic AST mutant survivors (5/17 relevant) clustered around asynckit/bounded.py's bound/limit validation guard -- an untested invalid-limit edge case (e.g. limit=0 or negative).

**Change**: Added a hidden test for the invalid-limit boundary, discriminating multiple of the clustered mutants at once. One further mutant declared equivalent.

**Historical comparability**: Old runs remain valid evidence for async-gather-bounded v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for async-gather-bounded (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, qwen2.5-coder:7b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 2 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, qwen2.5-coder:7b) since those are the scores most likely to change under the strengthened oracle.

---

### `async-retry`  v1.0.1 → v1.0.2

**Classification**: CONTRACT_AMBIGUITY (contract clarified)

**Finding**: A semantic mutant broadening 'except Exception' to 'except BaseException' (silently catching and retrying asyncio.CancelledError instead of letting cancellation propagate) was ACCEPTED. The written contract didn't specify which exception types should trigger a retry vs. propagate immediately.

**Change**: Clarified task.json's description that only Exception subclasses trigger a retry and BaseException subclasses (cancellation, KeyboardInterrupt, SystemExit) must propagate immediately -- resolved toward this reading because the reference already implements it and it matches standard asyncio convention. Added a hidden test asserting CancelledError propagates immediately without being retried or swallowed. One further generic mutant (a deleted None-initializer, provably overwritten before any read) declared equivalent.

**Historical comparability**: Old runs remain valid evidence for async-retry v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for async-retry (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **qwen2.5-coder:7b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 1 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (qwen2.5-coder:7b) since those are the scores most likely to change under the strengthened oracle.

---

### `async-timeout`  v1.0.0 → v1.0.1

**Classification**: GENUINE_ORACLE_GAP

**Finding**: Two declared controls (never_cancels_on_timeout, shield_leak) leaked the timed-out task while still correctly raising TimeoutError. Root cause: the only cancellation test checked a cleanup flag AFTER asyncio.run() returned; asyncio.run's own shutdown sweep force-cancels any still-pending task before closing the loop, masking both defects.

**Change**: Rewrote test_coroutine_is_cancelled_on_timeout to check, from inside the still-running driver coroutine right after with_timeout raises, that the exact task object that ran the timed-out coroutine (captured via asyncio.current_task(), immune to GC-timing nondeterminism) is done, and that no extra task remains in asyncio.all_tasks(). Verified: both controls flip to rejected_by_hidden_test, reference (1.0, True) x3 and the manual_wait_and_cancel alternative unaffected.

**Historical comparability**: Old runs remain valid evidence for async-timeout v1.0.0; they are NOT directly comparable to v1.0.1's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for async-timeout (v1.0.0 -> v1.0.1); the 30 stored runs at v1.0.0 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.1.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 1 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 1 |
| qwen3.5:9b | 5 | 3 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `expression-evaluator`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP (contract clarified)

**Finding**: An UNCAPPED mutation run (the original pack audit capped at 40/112 candidates) found a genuine infinite-loop bug: an unsupported character (e.g. 'a' in '2+a') routes into the tokenizer's digit-scan branch with no position advance, hanging forever instead of raising. Also found two contract ambiguities: unary-plus support (named operator, but only unary MINUS was called out) and the required exception type for malformed input (unspecified).

**Change**: Clarified task.json's description on both ambiguous points (both resolved toward what the reference AND the independently-written alternative already agreed on) before adding tests: an isolated hang-proof test for the invalid-character case (asserting ValueError, not a hang), a unary-plus test, and a missing-operand-must-raise-ValueError test. Three further generic mutants confirmed equivalent.

**Historical comparability**: Old runs remain valid evidence for expression-evaluator v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for expression-evaluator (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **qwen2.5-coder:7b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 1 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (qwen2.5-coder:7b) since those are the scores most likely to change under the strengthened oracle.

---

### `fix-list-dedup`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: The no-op (unmodified, set()-based) snapshot scored exactly T_hidden=0.500, the framework's documented gate-2 warning ceiling. Hand-confirmed root cause: 3 of 6 hidden tests provide zero real discriminating signal for this bug -- one trivially passes on an empty list, one has no actual duplicates to reorder (passes regardless of dedup correctness), and one coincidentally matches CPython's small-int set-iteration order under the sandbox's fixed PYTHONHASHSEED=0.

**Change**: Added genuinely order-discriminating hidden tests using non-ascending value permutations chosen so a set()-based implementation's likely output order provably differs from the correct first-occurrence order for that exact input -- strengthening the suite's actual discriminating power rather than reweighting existing tests to silence the warning.

**Historical comparability**: Old runs remain valid evidence for fix-list-dedup v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for fix-list-dedup (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 5 |
| gemma2:2b | 5 | 1 |
| llama3.2:latest | 5 | 3 |
| qwen2.5-coder:3b | 5 | 2 |
| qwen2.5-coder:7b | 5 | 5 |
| qwen3.5:9b | 5 | 5 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `fix-path-traversal`  v1.0.1 → v1.0.2

**Classification**: CONTRACT_AMBIGUITY (contract clarified)

**Finding**: A generic mutant disabling the per-part absolute-component guard survived for a specific input where an absolute part's string happens to already read as 'inside' base after normalization (e.g. safe_join('/srv/data', '/srv/data/logs/app.log')). The written contract ('raise if the result escapes base via an absolute component') doesn't unambiguously forbid accepting this on a literal reading, since the resulting string does not itself escape base.

**Change**: Clarified task.json's description that the absolute-component check is unconditional, independent of where the resulting string would land -- resolved this way because the reference and every declared control/alternative already independently encode an unconditional check. Added a hidden test for this exact discriminating input.

**Historical comparability**: Old runs remain valid evidence for fix-path-traversal v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for fix-path-traversal (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  No model previously passed this task — re-evaluation still required for a current claim, but no stored score is at risk of flipping from pass to fail.

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 0 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (none previously passed) since those are the scores most likely to change under the strengthened oracle.

---

### `grid-paths`  v1.0.0 → v1.0.1

**Classification**: GENUINE_ORACLE_GAP

**Finding**: Generic AST mutant survivors (6/22 relevant, the highest count among non-capped tasks), clustered at one line suggesting an untested boundary case (a degenerate grid or a blocked start/end cell).

**Change**: Added a hidden test for the untested boundary case.

**Historical comparability**: Old runs remain valid evidence for grid-paths v1.0.0; they are NOT directly comparable to v1.0.1's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for grid-paths (v1.0.0 -> v1.0.1); the 30 stored runs at v1.0.0 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.1.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 3 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 2 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 2 |
| qwen3.5:9b | 5 | 2 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `mask-secrets`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: A word-boundary-anchored-regex semantic mutant was ACCEPTED: it wraps every secret pattern in \b anchors, so a secret glued directly onto adjacent text with no delimiter (e.g. 'leakedsk-<20+ chars>') is left unredacted. The written contract defines an API key purely as a substring shape ('sk-' + 20+ alphanumeric chars) with no delimiter requirement.

**Change**: Added hidden tests asserting an API key and a bearer token glued to preceding text (no whitespace/punctuation boundary) are still redacted. Explicitly verified the declared alternative control (span_merge_rebuild) does not share this bug.

**Historical comparability**: Old runs remain valid evidence for mask-secrets v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for mask-secrets (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 2 |
| qwen2.5-coder:3b | 5 | 1 |
| qwen2.5-coder:7b | 5 | 5 |
| qwen3.5:9b | 5 | 3 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `merge-intervals`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: Generic AST mutant survivors (3/12 relevant, all change_constant family) suggesting an untested adjacent-but-not-overlapping interval boundary (e.g. [1,2] and [2,3]).

**Change**: Added a hidden test for the adjacent-interval boundary case.

**Historical comparability**: Old runs remain valid evidence for merge-intervals v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for merge-intervals (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 1 |
| qwen2.5-coder:3b | 5 | 1 |
| qwen2.5-coder:7b | 5 | 5 |
| qwen3.5:9b | 5 | 2 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `paginator`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: num_pages = total_items // per_page + 1 was accepted because every existing hidden test used a non-exact-multiple (total_items, per_page) pair, where this bug coincidentally matches the correct ceiling.

**Change**: Added a test using an exact-multiple pair (9, 3) asserting num_pages == 3 (not 4) and that page(4) raises ValueError. Verified: control flips to rejected_by_hidden_test, all other controls unaffected.

**Historical comparability**: Old runs remain valid evidence for paginator v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for paginator (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 1 |
| qwen2.5-coder:3b | 5 | 2 |
| qwen2.5-coder:7b | 5 | 5 |
| qwen3.5:9b | 5 | 1 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `query-builder`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: where("") was silently dropped instead of always being recorded as a call, though the contract is explicitly call-count-based ('if at least one where() was called').

**Change**: Added a test asserting Query().where("").build() == 'SELECT * WHERE '. Also investigated and ruled out the prior audit's 'possible adapter confound' concern for this task's low historical model pass rate -- every hidden assertion is directly derivable from the written formatting rules and a structurally different alternative is cleanly accepted; no evidence of an overfitted grader.

**Historical comparability**: Old runs remain valid evidence for query-builder v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for query-builder (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 2 |
| qwen3.5:9b | 5 | 2 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `refactor-order-validation`  v1.0.2 → v1.0.3

**Classification**: GENUINE_ORACLE_GAP

**Finding**: An UNCAPPED mutation run (original capped at 40/72) found genuine gaps in a dict-key guard (orderkit/process.py) and a corrupted divisor constant (orderkit/money.py). Also investigated the hidden_import_closure.gate7 WARNING (imports both orderkit/__init__.py and orderkit/process.py) and confirmed it BENIGN -- a normal parent-package import in a 3-file refactor task, not a separate oracle-helper module.

**Change**: Added hidden tests for the dict-guard and divisor-constant gaps. Declared 3 further generic mutants equivalent (a deleted __all__ list, a boundary operator and a constant change both on a provably-unreachable branch at process.py:56).

**Historical comparability**: Old runs remain valid evidence for refactor-order-validation v1.0.2; they are NOT directly comparable to v1.0.3's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for refactor-order-validation (v1.0.2 -> v1.0.3); the 30 stored runs at v1.0.2 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.3.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 1 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 5 |
| qwen3.5:9b | 5 | 2 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `result-type`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: map() on an ok Result mutated self and returned self instead of constructing a NEW Result, though the contract explicitly promises 'a NEW ok Result'. No test checked object identity or that the original survives map() unmutated.

**Change**: Added a test asserting the returned object is not the original and the original still unwraps to its pre-map value. Verified two independent ways (engine run + isolated pytest reproduction 3x).

**Historical comparability**: Old runs remain valid evidence for result-type v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for result-type (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, qwen2.5-coder:3b, qwen2.5-coder:7b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 2 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 1 |
| qwen2.5-coder:7b | 5 | 3 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, qwen2.5-coder:3b, qwen2.5-coder:7b) since those are the scores most likely to change under the strengthened oracle.

---

### `sanitize-filename`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: An over-restrictive character-allowlist known-bad control ('strict_allowlist') was ACCEPTED: it correctly implements all 5 documented unsafe-input checks but additionally rejects any name containing a character outside [A-Za-z0-9._-] (space, punctuation, non-ASCII), which is not one of the 5 documented conditions. Every prior 'must accept' hidden test used only letters/digits/dots.

**Change**: Added hidden tests asserting a name with a space, an ordinary punctuation character, and a non-ASCII character are all returned UNCHANGED, per the documented contract ('unchanged unless one of 5 listed unsafe conditions'). Also declared two generic AST mutants at safename/name.py:27 equivalent (a dead-code '..' component check, provably unreachable once separators are already rejected earlier).

**Historical comparability**: Old runs remain valid evidence for sanitize-filename v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for sanitize-filename (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 3 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 2 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 3 |
| qwen3.5:9b | 5 | 2 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, llama3.2:latest, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `top-k-frequent`  v1.0.2 → v1.0.3

**Classification**: GENUINE_ORACLE_GAP

**Finding**: Generic AST mutant survivors (2/13 relevant, remove_branch + boundary_operator at the same line) suggesting an untested tie-breaking or k-out-of-range boundary.

**Change**: Added a hidden test for the tie-breaking/k-boundary case.

**Historical comparability**: Old runs remain valid evidence for top-k-frequent v1.0.2; they are NOT directly comparable to v1.0.3's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for top-k-frequent (v1.0.2 -> v1.0.3); the 30 stored runs at v1.0.2 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.3.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, gemma2:2b, qwen2.5-coder:7b, qwen3.5:9b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 2 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 1 |
| qwen3.5:9b | 5 | 2 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, gemma2:2b, qwen2.5-coder:7b, qwen3.5:9b) since those are the scores most likely to change under the strengthened oracle.

---

### `toposort`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: A 'drop all dependencies but the first' known-bad control was ACCEPTED by test_multiple_implicit_dependencies: the original test graph's expected order was rescued by an unrelated alphabetical-tiebreak coincidence, not because the dropped edge was actually enforced.

**Change**: Rewrote the test's graph so the dropped edge is the only thing that can produce the correct relative order (a dependency name chosen to sort AFTER the dependent, so the tiebreak can no longer rescue a dropped-edge implementation). Declared one generic AST mutant (indegree initial-value 0 vs 1) equivalent -- the very next loop unconditionally overwrites it for every node before any read.

**Historical comparability**: Old runs remain valid evidence for toposort v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

> **Note**: CORRECTED by the orchestrating session during independent review: the authoring agent's original conclusion (reevaluation_required=False) reasoned that because the integrity engine's own prior audit already flagged this task INVALID via a synthetic known-bad control, no real historical model run was affected. That conflates two unrelated facts: the engine's synthetic-control verdict says nothing about whether any of this task's 30 real historical runs (6 models x 5 reps, all at v1.0.1, 0 of which reached functional_pass=True -- toposort is a hard task no model solved) happened to exhibit the same defect class. The hidden test's grading behavior materially changed regardless (test_multiple_implicit_dependencies now uses a different graph), so all 30 v1.0.1 runs are old-instrument evidence, exactly like every other version-bumped task in this batch -- re-evaluation is required to make any current claim, corrected to True here.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  No model previously passed this task — re-evaluation still required for a current claim, but no stored score is at risk of flipping from pass to fail.

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 0 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 0 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (none previously passed) since those are the scores most likely to change under the strengthened oracle.

---

### `validate-redirect-url`  v1.0.1 → v1.0.2

**Classification**: GENUINE_ORACLE_GAP

**Finding**: A substring-host-match known-bad control ('allowed_host in hostname' instead of exact equality) was ACCEPTED -- no test used a host merely containing the allowed host as a substring (e.g. app.example.com.evil.com). Independent re-verification of a prior hand-trace also found it INCOMPLETE: a protocol-relative-guard mutant is equivalent only for exactly-two-slash targets, not 3+ slashes (which parse with an empty netloc and slip past the later scheme check too).

**Change**: Added hidden tests for the substring-host-match gap and for 3+-slash protocol-relative targets ('///evil.com', '////evil.com'). Two other generic mutants confirmed genuinely equivalent (an And/Or swap and a netloc-guard mutant), two more genuine gaps found and fixed (non-string/empty target, no-leading-slash relative path).

**Historical comparability**: Old runs remain valid evidence for validate-redirect-url v1.0.1; they are NOT directly comparable to v1.0.2's grading since hidden-test behavior changed. Re-evaluation required for any current benchmark claim against this task.

**Re-evaluation required**: True

*Rationale*: Hidden-test grading behavior materially changed for validate-redirect-url (v1.0.1 -> v1.0.2); the 30 stored runs at v1.0.1 were graded against the OLD instrument and remain valid evidence FOR that version, but are not directly comparable to v1.0.2.

**Known affected model runs**: 30 total (deepseek-coder:6.7b, gemma2:2b, llama3.2:latest, qwen2.5-coder:3b, qwen2.5-coder:7b, qwen3.5:9b)
  Prior PASS (highest re-eval priority): **deepseek-coder:6.7b, qwen2.5-coder:7b**

| Model | n | prior passes |
|---|---|---|
| deepseek-coder:6.7b | 5 | 1 |
| gemma2:2b | 5 | 0 |
| llama3.2:latest | 5 | 0 |
| qwen2.5-coder:3b | 5 | 0 |
| qwen2.5-coder:7b | 5 | 3 |
| qwen3.5:9b | 5 | 0 |

**Recommended action**: Re-run all 6 models against the new task version before citing any leaderboard claim for this task; prioritize models that previously PASSED (deepseek-coder:6.7b, qwen2.5-coder:7b) since those are the scores most likely to change under the strengthened oracle.

---
