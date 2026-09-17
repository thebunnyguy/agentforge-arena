# Qwen 3.5 9B evaluation report

**Model:** `qwen3.5:9b`

**Job:** `eb54c065c0b84d099a82570f4aeee83c` (`succeeded`)

**Run:** 2026-09-17 15:15:07 IST to 2026-09-17 17:19:05 IST (2h 3m 58s elapsed)

**Source:** local app job metadata and job-linked run IDs 1101–1220; the attempt evidence is preserved in [`runs.sqlite`](runs.sqlite). Extracted on 2026-09-17.

## Result

| Measure | Result |
|---|---:|
| Functional passes | **40/120 (33.33%)** |
| 95% Wilson interval for pass rate | 25.53%–42.17% |
| Mean continuous score (0–1) | 0.5056 |
| Completed valid attempts | 84 |
| Timed out attempts | 36 (30%) |
| Nonpassing valid attempts | 44 |
| Voided infrastructure attempts | 0 |
| Tasks passed at least once | 14/24 |

The job finished successfully and recorded all 120 planned attempts. “Succeeded” describes job completion; the model passed 40 attempts. Timeouts count as failures under the benchmark’s scoring rules.

## Evaluation setup

- Backend: `ollama` at `http://localhost:11434`.
- Scope: 24 tasks × 5 attempts per task; no runs were reused.
- Base seed: `42`; temperature: `0.6`; model request timeout: `180` seconds. Individual task wall-clock limits in task specifications also apply.
- Scoring version: `v0.1` for every attempt. A functional pass requires all hard gates and hidden tests; the continuous score gives partial credit when eligible. A timeout scores zero and remains in the denominator.
- The stored model name identifies the requested Ollama model. The database does not record its digest, hardware, or full generation transcript.

## Results by task

Each row includes five attempts. Mean score includes timed out attempts as zero.

| Task | Version | Passes | Timeouts | Mean score |
|---|---:|---:|---:|---:|
| `escape-html` | 1.0.1 | 5/5 | 0/5 | 1.000 |
| `fix-binary-search` | 1.0.0 | 5/5 | 0/5 | 1.000 |
| `fix-list-dedup` | 1.0.1 | 5/5 | 0/5 | 1.000 |
| `async-retry` | 1.0.1 | 0/5 | 1/5 | 0.500 |
| `async-timeout` | 1.0.0 | 3/5 | 0/5 | 0.700 |
| `fix-roman-numerals` | 1.0.0 | 3/5 | 0/5 | 0.644 |
| `implement-lru-cache` | 1.0.1 | 3/5 | 0/5 | 0.829 |
| `mask-secrets` | 1.0.1 | 3/5 | 1/5 | 0.657 |
| `merge-intervals` | 1.0.1 | 2/5 | 0/5 | 0.700 |
| `paginator` | 1.0.1 | 1/5 | 4/5 | 0.200 |
| `result-type` | 1.0.1 | 0/5 | 1/5 | 0.644 |
| `sanitize-filename` | 1.0.1 | 2/5 | 1/5 | 0.580 |
| `async-batched` | 1.0.2 | 0/5 | 0/5 | 0.783 |
| `async-first-success` | 1.0.1 | 0/5 | 2/5 | 0.133 |
| `async-gather-bounded` | 1.0.1 | 0/5 | 1/5 | 0.086 |
| `fix-path-traversal` | 1.0.1 | 0/5 | 0/5 | 0.800 |
| `grid-paths` | 1.0.0 | 2/5 | 3/5 | 0.400 |
| `query-builder` | 1.0.1 | 2/5 | 0/5 | 0.600 |
| `refactor-order-validation` | 1.0.2 | 2/5 | 1/5 | 0.400 |
| `top-k-frequent` | 1.0.2 | 2/5 | 3/5 | 0.400 |
| `toposort` | 1.0.1 | 0/5 | 3/5 | 0.077 |
| `two-sum-indices` | 1.0.1 | 0/5 | 5/5 | 0.000 |
| `validate-redirect-url` | 1.0.1 | 0/5 | 5/5 | 0.000 |
| `expression-evaluator` | 1.0.1 | 0/5 | 5/5 | 0.000 |

## Observations

- All five attempts passed on `escape-html`, `fix-binary-search`, and `fix-list-dedup`.
- Ten tasks had no functional pass. The last three tasks in the job order—`two-sum-indices`, `validate-redirect-url`, and `expression-evaluator`—timed out on all five attempts each.
- `async-batched` and `fix-path-traversal` had no functional pass despite mean continuous scores of 0.783 and 0.800. These scores reflect partial hidden-test success, not completed tasks.
- Captured patches were nonempty in 95/120 attempts. Stored grading includes test results for every attempt; a hidden-test row is absent for one attempt. The records do not establish a root cause for each timeout or failure.

## Interpretation and limits

This is the outcome of one local benchmark job with five attempts per task. Its 33.33% observed pass rate includes timeouts, as required by the benchmark. The Wilson interval describes sampling uncertainty for the pooled 120 attempts; attempts on the same task may be correlated, so it should not be read as a general capability guarantee. The 24 task versions recorded in this job match the current task specifications.

The database stores scores, statuses, timings, test outcomes, patches, and transcript hashes, but not full transcripts or the exact model digest. Timeout causes and model-level failure explanations cannot be confirmed from these records alone.

## Source records

- Job metadata and events were read from the local app database using job ID `eb54c065c0b84d099a82570f4aeee83c`.
- Attempt-level evidence is preserved in `runs`, `run_scores`, `diffs`, and `test_results` in [`runs.sqlite`](runs.sqlite); run IDs 1101–1220.
- Scoring definitions: [`../docs/EVALUATION_FRAMEWORK.md`](../docs/EVALUATION_FRAMEWORK.md) and the repository’s scoring implementation.

## Appendix: Task descriptions and evaluation terms

### What every task package contains

Each task is a small Python repair or implementation exercise. Its benchmark package contains:

- a pristine starting snapshot given to the model;
- a written API and behavior contract;
- an allow-list identifying the source package the model may edit;
- visible tests for basic feedback;
- hidden tests for acceptance and edge cases;
- regression tests to detect damage to existing behavior; and
- a reference implementation used to validate the benchmark, not as model input.

The **difficulty** values below are manual benchmark labels from 2 (easier) to 5 (hardest in this pack). The **time limit** is the task's wall-clock budget and can be lower than the 180-second model request timeout configured for the job.

### The 24 evaluated tasks

| Task | What it tests and requires | Type / difficulty | Editable package | Time limit |
|---|---|---:|---|---:|
| `escape-html` | Repair HTML escaping for `&`, `<`, `>`, double quotes, and single quotes. Ampersands must be escaped first to prevent double escaping. | Bug fix / 2 | `htmlesc/**` | 60s |
| `fix-binary-search` | Repair `bisect_left` so it returns the leftmost valid insertion index for a target in a sorted list, including boundary cases. | Bug fix / 2 | `searchkit/**` | 120s |
| `fix-list-dedup` | Remove duplicate list items while preserving the order of their first appearance. | Bug fix / 2 | `listkit/**` | 120s |
| `async-retry` | Implement asynchronous retry using a fresh coroutine for each attempt; return the first success or re-raise the last exception. | Feature / 3 | `aretry/**` | 60s |
| `async-timeout` | Await a coroutine within a deadline; on expiry, raise `TimeoutError` and cancel the underlying coroutine without leaking a running task. | Feature / 3 | `atimeout/**` | 60s |
| `fix-roman-numerals` | Repair Roman numeral parsing so subtractive pairs such as `IV` and `IX` produce the correct value. | Bug fix / 3 | `romankit/**` | 120s |
| `implement-lru-cache` | Implement `get` and `put` for a capacity-bound least-recently-used cache. Both reads and writes must refresh recency, and overflow must evict the least recently used entry. | Feature / 3 | `cachekit/**` | 120s |
| `mask-secrets` | Replace API keys, bearer tokens, and email addresses with `[REDACTED]` while leaving ordinary text unchanged. Only regular-expression logic is allowed; no network access. | Feature / 3 | `maskkit/**` | 60s |
| `merge-intervals` | Sort and merge overlapping or touching integer intervals, including unsorted input. | Feature / 3 | `intervalkit/**` | 120s |
| `paginator` | Implement page counts, page bounds, zero-based start and exclusive end indexes, previous/next flags, and invalid-page errors. | Feature / 3 | `paginate/**` | 60s |
| `result-type` | Implement a Rust-style success/error container with `ok`, `err`, `is_ok`, `unwrap`, `unwrap_or`, and `map`; error values must bypass the mapping function. | Feature / 3 | `resultkit/**` | 60s |
| `sanitize-filename` | Accept a safe single filename and reject empty names, dot entries, path separators, null bytes, and traversal components. No real filesystem access is allowed. | Bug fix / 3 | `safename/**` | 60s |
| `async-batched` | Run coroutine factories concurrently within fixed-size batches, process batches sequentially, and return results in input order. | Feature / 4 | `abatch/**` | 60s |
| `async-first-success` | Run all coroutine factories concurrently, return the first successful result, cancel the remaining work, and raise the last input-ordered exception if every coroutine fails. | Feature / 4 | `afirst/**` | 60s |
| `async-gather-bounded` | Gather asynchronous results in input order while enforcing a maximum number of in-flight coroutines and propagating the first exception. | Feature / 4 | `asynckit/**` | 120s |
| `fix-path-traversal` | Join path components under a base path and reject absolute or `..` based escapes. The solution must use POSIX path string logic without filesystem access. | Security bug fix / 4 | `safepath/**` | 120s |
| `grid-paths` | Count right/down paths across a grid, including the `1×1` case, with dynamic programming, memoization, or a binomial formula. Exponential recursion is too slow. | Performance feature / 4 | `gridpaths/**` | 20s |
| `query-builder` | Implement a chainable SQL builder with exact `SELECT`, optional combined `WHERE`, and optional `LIMIT` formatting in that order. | API feature / 4 | `qbuild/**` | 60s |
| `refactor-order-validation` | Split a working order-processing function into `validate_items`, `subtotal`, and `apply_coupon` helpers without changing observable behavior. | Refactor / 4 | `orderkit/**` | 120s |
| `top-k-frequent` | Return the `k` most frequent items with ties resolved by first appearance. The solution must use an efficient counting pass rather than repeated list scans. | Performance feature / 4 | `topk/**` | 20s |
| `toposort` | Produce a deterministic dependency-first topological ordering with lexicographic tie-breaking and raise `CycleError` for any cycle or self-loop. | Feature / 4 | `graphkit/**` | 120s |
| `two-sum-indices` | Return distinct ordered indices whose values sum to the target, or `None`; the required approach is an efficient single pass with a lookup map. | Performance feature / 4 | `twosum/**` | 20s |
| `validate-redirect-url` | Permit a local single-slash path or an absolute URL on the allowed host; reject external hosts, protocol-relative targets, and dangerous schemes such as `javascript:` and `data:`. No network access is allowed. | Security bug fix / 4 | `saferedirect/**` | 60s |
| `expression-evaluator` | Parse `+`, `-`, `*`, `/`, parentheses, precedence, unary minus, integers, floats, and whitespace using a real parser. Calling `eval()` is forbidden. | Feature / 5 | `calckit/**` | 120s |

### Evaluation terms and conditions

1. **Five independent attempts per task.** Each attempt starts from a fresh copy of the task snapshot. A previous attempt's edits do not carry forward.
2. **Allowed scope.** The model may edit only the package listed above. Test files are protected and may not be changed. A protected or out-of-scope edit fails the scope gate.
3. **Clean-room grading.** The captured patch is applied to a separate pristine copy for grading. Hidden and regression tests are not taken from the model's working directory.
4. **Functional pass.** An attempt passes only when it produces a nonempty in-scope change, stays within its time limit, preserves regression behavior, and passes every hidden acceptance test.
5. **Partial score.** Passing only some hidden tests can produce a continuous score between 0 and 1 for diagnosis, but it does not count as a functional pass.
6. **Timeouts and model errors.** These count as failed attempts with a score of zero. Partial edits may still be retained for inspection.
7. **Infrastructure failures.** A confirmed platform, sandbox, or grader failure is voided and excluded from the pass-rate denominator. This job recorded no voided attempts.
8. **No test tampering or shortcuts.** Modifying tests, escaping the editable package, using forbidden facilities such as `eval()`, accessing the filesystem or network where prohibited, or replacing a required efficient method with an implementation that exceeds the time budget cannot earn a pass.
9. **Result interpretation.** The report measures performance on these exact task versions and rules. It does not establish general software-engineering ability outside this benchmark.
