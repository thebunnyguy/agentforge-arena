## 8. Benchmark design and anti-gaming

This section fixes how tasks are authored, validated, versioned, and defended against gaming. The benchmark itself gets a CI pipeline: a task is data, and bad data here corrupts every downstream statistic in Sections 1–7. Every defense below names the attack it blocks; every gate names the failure it prevents.

### 8.1 Task template

A task is a single YAML document, stored in PostgreSQL (JSONB) with the repo snapshot in content-addressed blob storage. The full annotated template:

```yaml
id: task.flask-auth.fix-session-expiry        # globally unique slug, immutable
version: 1.2.0                                 # semver; MAJOR = grading semantics change,
                                               # MINOR = tests/description change, PATCH = metadata only
title: "Fix session expiry off-by-one in auth middleware"
description_for_agent: |                       # the ONLY prose the agent sees; self-contained
  Sessions expire one hour late. Fix the expiry check in the auth
  middleware so sessions are invalid at exactly `expires_at`.
repo_snapshot:
  content_hash: "sha256:9f2c...a41"            # hash of canonical tar of the pristine repo
  storage: "blob://snapshots/9f2c...a41.tar.zst"  # content-addressed, immutable, offline store
setup_script: "scripts/setup.sh"               # runs in agent sandbox; failures classified
                                               # agent-attributable vs infra per gate setup_ok
domains:                                       # max 3 weighted tags (contract item 10)
  - {tag: backend, weight: 1.0}
  - {tag: security, weight: 0.5}
activity: debugging-bugfix                     # 4.1 vocabulary (canonical): debugging-bugfix |
                                               # feature-implementation | refactoring | test-writing |
                                               # migration | documentation. (Performance is a DOMAIN
                                               # tag, not an activity.)
scale: S                                       # 4.1 vocabulary: XS (<=10 changed LOC expected) |
                                               # S (<=50) | M (<=200) | L (>200 or repo-wide)
context_size_kloc: 2                           # KLOC the agent must read (4.1); required for M and L,
                                               # optional below
manual_difficulty: 2                           # mean of the four-facet 1-5 rubric (5.1), see 8.2 gate (6)
timeout_s: 900                                 # wall clock for the agent run; no_timeout gate
resource_limits: {cpu: 2, mem_mb: 4096, disk_mb: 2048, pids: 256}
network_policy: deny_all                       # deny_all | allowlist:[...]; default deny_all
allowed_tools: [shell, editor, python]         # sandbox capability allowlist
protected_paths:                               # scope_ok gate: any diff hunk here -> G=0.
                                               # Globs use gitignore (gitwildmatch) semantics, pinned —
                                               # a bare name like "conftest.py" is ambiguous across
                                               # glob implementations and is rejected by validation
  - "tests/**"
  - ".agentforge/**"
  - "**/conftest.py"                           # recursive: every conftest at any depth
visible_tests: "tests/visible/"                # mounted in agent sandbox; feedback only, NEVER scored
hidden_tests: "grader://tests/hidden/"         # stored OUTSIDE the snapshot; clean-room only
regression_tests: "tests/regression/"          # must pass before AND after the diff
scoring_recipe:
  hidden_test_weights:                         # weights for T_hidden; default 1.0 each
    test_expiry_boundary: 2.0                  # boundary case is the point of the task
    test_expiry_normal: 1.0
    test_expiry_timezone: 1.0
  q_overrides: {lint_weight: 0.0}              # task-level Q component overrides (e.g. legacy
                                               # repo where lint is meaningless)
metamorphic_variants:                          # see 8.3; each variant is a derived task version
  - {kind: identifier_rename, seed: 17}
  - {kind: paraphrase_description, ref: "variants/v1-desc.md"}
  - {kind: constant_shift, delta: "+3600", assertions_updated: true}
reference_solution: "blob://solutions/3be1...77.patch"  # private; used only by benchmark CI
provenance:
  origin: "github.com/example/flask-shop@a1b2c3"  # or 'synthetic'
  license: MIT                                  # must permit redistribution in the pack
author: "mkr"
review_state: draft                             # draft -> in_review -> active -> deprecated
```

Decision: `hidden_tests` and `reference_solution` are never inside `repo_snapshot`. They live in a separate grader-only store keyed by task id+version, so no path traversal or archive inspection inside the agent sandbox can reach them.

### 8.2 Activation gates: the benchmark's own CI

A task moves `in_review -> active` only when its activation gates pass. The gates are staged to match the roadmap (Section 11): **v0.1 requires gates (1), (2), (3), (6), and (7)** — all cheap and automatable by one person. **Gate (4) and the >= 1 metamorphic-variant requirement of 8.3 activate in v0.2**, alongside the rest of the task-health machinery; tasks activated under v0.1 are re-gated when v0.2 lands. **Gate (5) is required whenever a second reviewer exists**; for a one-person team it is recorded as `waived` in the task's review record rather than blocking activation. The pipeline is fully automated except gate (5).

1. **Reference solution check.** Apply `reference_solution` to the pristine snapshot in the grader sandbox; it must score exactly S = 1.0 (G = 1, T_hidden = 1, Q at ceiling for the recipe) on **3 consecutive regrades with byte-identical grader output**. Catches: flaky hidden tests, nondeterministic grading, broken scoring recipes.
2. **Unmodified snapshot must FAIL hidden tests.** Grade the empty diff: T_hidden must be < 1 (decision: require at least one weighted hidden test failing with weight share >= 0.5, so the task cannot be passed by doing nothing or nearly nothing). Catches: tasks that test nothing.
3. **Unmodified snapshot must PASS regression tests.** Otherwise `regression_pass` would punish agents for pre-existing breakage. Catches: rotten snapshots.
4. **Mutation adequacy.** Run mutation testing (mutmut for Python, cosmic-ray as alternative; both offline) on the modules touched by the reference solution, grading each mutant with the hidden suite. Require:

```
kill_rate = killed_mutants / generated_mutants >= 0.70
```

`killed_mutants` = mutants on which at least one hidden test fails; `generated_mutants` = total non-equivalent mutants emitted (timeout-surviving mutants count as killed only if the kill is via test failure, not the harness timeout). Worked example: 30 mutants generated on the touched modules, hidden suite fails on 23 of them: kill_rate = 23/30 = 0.767 >= 0.70, gate passes. At 20/30 = 0.667 the gate fails and the author must strengthen the hidden suite. Rationale: a suite that cannot kill simple mutants cannot distinguish a correct diff from a near-miss, so T_hidden would be noise.
5. **Two-human ambiguity check.** A second person who has not seen the hidden tests implements from `description_for_agent` alone. If their reasonable solution fails the hidden suite, the description is ambiguous: rewrite the description (MINOR bump) or relax the tests, then repeat gates 1–5. Catches: hidden requirements not stated in the description — the most common authoring failure.
6. **Difficulty rubric recorded.** `manual_difficulty` is authored with the four-facet rubric of Section 5.1 — expected human time, files touched, spec ambiguity, domain depth, each scored 1–5 — and recorded as the facet mean (Section 5 rescales it to d_rubric = (mean - 1)/4 for the MISCALIBRATED check). The behavioral anchors — 1 = single-line fix, location given; 2 = single-file fix, location findable by grep; 3 = multi-file change, one subsystem; 4 = cross-subsystem change or non-obvious root cause; 5 = requires design decision among multiple valid architectures — are calibration guidance for authors scoring the facets, not the score itself. This is a prior only; v0.2 replaces it operationally with empirical d_t = 1 - (c_pool+1)/(n_pool+2). Worked example: a task with pooled c_pool = 4 passes out of n_pool = 20 runs gets d_t = 1 - 5/22 = 0.7727; if its manual_difficulty was 1 (d_rubric = 0), then |d_rubric - d_t| = 0.7727 > 0.5 raises the MISCALIBRATED task-health flag per 5.1.
7. **Hidden-test import closure.** Statically resolve every import in the hidden suite against the repo snapshot. Every repo module the hidden tests import must be either (a) the code under test or (b) covered by `protected_paths`; otherwise the gate fails and the authoring tool suggests adding the module. Catches: oracle helpers — e.g. a non-test fixture module the hidden tests use to compute expected values — left editable, which would let an agent rewrite the oracle to force hidden tests to pass without ever tripping `scope_ok`.

Any gate failure keeps the task out of every pack and out of every statistic.

### 8.3 Anti-cheating defenses

Each defense is listed with the attack it blocks. All are deterministic and offline (contract item 12).

| Defense | Attack blocked |
|---|---|
| Clean-room grading: captured diff applied to pristine snapshot in a separate grader sandbox | Environment poisoning, tampering with installed test deps, leaving daemons/cron jobs that fake results, monkeypatching the runner |
| Protected paths + `scope_ok` gate (G = 0 on violation) | Editing tests, conftest, CI config, or grader hooks inside the workspace |
| Hidden/visible split; hidden tests never mounted in the agent sandbox | Reading test files to extract expected values. Because the files are physically absent, the trace detector for hidden-test access attempts is a **tripwire that must never fire**; any fire indicates a harness packaging bug and halts the pack |
| Hardcoding detector (below) | Returning literal expected outputs instead of computing them |
| Metamorphic variants (below) | Memorized solutions, lookup-table answers keyed on surface form |
| Property-based hidden tests (hypothesis, fixed seed) | Solutions overfit to the example inputs the visible tests happen to use |
| Public dev pack vs private eval pack; private pack never published, never used in agent prompts or docs | Training/tuning directly on the graded tasks |
| Pack/version pinning of all scores | Silent apples-to-oranges comparisons after task edits |
| Trace tripwires: network syscalls under `deny_all`, writes outside the workspace, sleep-to-timeout patterns (>50% of wall clock idle then timeout), clock manipulation (settimeofday, faketime) | Exfiltration attempts, timeout gaming, time-dependent test evasion. Decision: tripwires flag the run `SUSPECT` for human review; they do not auto-zero, because false positives (e.g. legitimate retries that look like sleeps) would corrupt p-hat |

**Hardcoding detector.** A unified diff is not parseable into an AST, so the procedure works on the patched tree: apply the diff to the pristine snapshot, parse each touched file with a per-language parser (Python: stdlib `ast`; JS/TS and other supported languages: tree-sitter grammars — all offline), and collect L_diff, the set of string and numeric literal nodes whose line numbers fall inside added-hunk ranges. L_hidden is the set of expected values appearing in hidden-test assertions. For a touched file in a language with no parser available, the detector is skipped and the grader report records `detector unavailable` — never a silent pass. After removing a stoplist (0, 1, -1, "", None, True, False, common HTTP codes):

```
overlap = |L_diff intersect L_hidden| / |L_hidden|
flag if overlap > 0.5 AND |L_diff intersect L_hidden| >= 3
```

If L_hidden is empty after the stoplist, overlap is undefined and the detector is skipped for that task. Worked example: hidden assertions contain 6 distinctive expected literals; the diff contains 4 of them verbatim: overlap = 4/6 = 0.667 > 0.5 and 4 >= 3, so the run is flagged. Decision: this is a heuristic reviewed by a human, never an automatic S = 0 — legitimate solutions sometimes share constants with tests (e.g. protocol magic numbers).

**Metamorphic variants and contamination score.** From v0.2 (per the gate staging in 8.2), each active task ships >= 1 variant: identifier renames, paraphrased description, or shifted constants with correspondingly shifted hidden assertions (so the variant is exactly as hard). For agent a on task t, let score_original and score_variant be mean S over the standard n runs on each form:

```
contamination = (score_original - score_variant) / score_original
flag if contamination > 0.3 AND the bootstrap 95% CIs of the two means do not overlap
```

The ratio is undefined when score_original = 0; such pairs are skipped — an agent that fails the original outright has nothing memorized to detect.

Worked example: score_original = 0.92, score_variant = 0.55: contamination = (0.92 - 0.55)/0.92 = 0.402 > 0.3; if the percentile-bootstrap CIs over the n runs per form also fail to overlap, the pair is flagged as likely memorization. The flag goes to human review before anything changes — consistent with the hardcoding detector and the trace tripwires, nothing here auto-substitutes or auto-zeroes. The report always shows both scores; a reviewer who confirms memorization marks the pair so that only the variant score feeds the headline. The point-ratio alone is too noisy to act on: with n = 5 runs per form, a genuinely clean agent at score_original = 0.6 and score_variant = 0.4 already yields contamination = 0.33 from sampling noise alone (the standard deviation of the difference of two means of 5 near-binary run scores is ~0.3), so the CI condition is required, and the expected noise band is derived from the observed run-to-run variance s of each pair rather than asserted globally.

**Variant generation.** The generator is deterministic and offline. `identifier_rename`: tree-sitter parses the snapshot and renames a seeded, deterministic sample of repo-local identifiers; the same rename map is applied simultaneously to the repo snapshot, the hidden suite, and the reference patch, so the variant stays exactly as hard as the original. `constant_shift`: a declared (constant, delta) pair applied to the snapshot, with a mechanical rewrite of every hidden assertion that depends on the constant (`assertions_updated: true` in the template records that the rewrite ran). `paraphrase_description`: manually authored prose (the `ref` file in the template) — no automation is claimed for natural language. Every generated variant must re-pass activation gates (1)–(3) before it is used in any contamination comparison; a variant that fails them is discarded and regenerated under a new seed, never patched by hand.

**Cross-version overfit check.** When pack version P_new replaces P_old, compute per agent delta = p-hat(P_old) - p-hat(P_new) over the shared task lineage. Report the delta with both Wilson intervals; an agent dropping from 0.80 to 0.55 while the cohort median drops 0.05 was overfit to P_old. Decision: this is a published diagnostic, not a penalty — the fork in the time series (below) already prevents the old score from carrying over.

### 8.4 Contamination controls for local LLMs (Ollama)

Local models have frozen training sets, so contamination is about the base model, not adaptation during the eval.

- **Source selection.** Prefer tasks built from repos or commits dated after the model's published training cutoff, or from synthetic repos generated in-house. Recorded in `provenance`; the pack manifest reports the fraction of post-cutoff tasks per model under test.
- **Memorization probe.** Present the first 60% of `description_for_agent` (and separately, the pre-fix buggy function body) to the model as a raw completion prompt, temperature 0. If the continuation matches the held-out remainder for >= 30 consecutive tokens verbatim, mark the (model, task) pair `contamination_suspect`. This is cheap and fully offline. It is also **imperfect and we say so**: it catches verbatim memorization only, not paraphrastic familiarity, and a negative probe is weak evidence of cleanliness. It complements, never replaces, metamorphic variants — the variant delta is the stronger signal.

### 8.5 Versioning and comparability

Scores are comparable **only** within the triple `(task_version, pack_version, harness_version)`. Any bump to any element forks the time series: the leaderboard shows the new lineage from zero history, and the old lineage is frozen read-only. Decision: no cross-version score adjustment or equating in v0.x/v1.0 — equating methods (IRT linking) are deferred until two pack versions share enough anchor tasks, and even then they will be reported alongside, not instead of, the forked series. PostgreSQL enforces this: the unique key on aggregated results includes all three version columns, making accidental pooling impossible at the schema level.

### 8.6 Authoring guidance

A **good task** has: a single clear goal stated entirely in the description; hidden tests that check observable behavior, not implementation; a realistic repo context (real dependency graph, existing conventions to follow); deterministic tests — no wall-clock assertions, no network, no test-order coupling, fixed seeds for any randomness; and multiple valid solution paths (verified implicitly by gate 5: the second human rarely reproduces the reference implementation).

**Antipatterns** (rejected at review):

- **Implementation-pinning tests** — hidden tests asserting private function names, call counts, or exact log strings; they grade conformity, not correctness.
- **Hidden requirements** — behavior graded but never stated; gate 5 exists to catch exactly this.
- **Flaky timing assertions** — `assert elapsed < 0.1` style checks; they convert machine load into score noise and break grader determinism (gate 1).
- **Visible tests that fully specify hidden ones** — if passing visible implies passing hidden, the hidden suite adds nothing and the visible suite becomes the Goodhart target it was designed not to be. Rule of thumb at review: hidden tests must cover at least one equivalence class and one boundary absent from the visible suite.
- **Trivia tasks** — solvable by recalling a known upstream patch verbatim; prefer post-cutoff or synthetically perturbed sources (8.4).

### Limitations

- The mutation kill threshold (70%) is a blunt proxy for test adequacy: equivalent-mutant detection is undecidable, mutmut's operators are syntactic, and a suite can clear 70% while missing the semantic core of a task. The threshold was chosen as a floor, not a guarantee.
- The hardcoding detector and trace tripwires are heuristics with known false positives and require human review; at scale (thousands of runs) review becomes the bottleneck, and v2.0's learned trace classifier only prioritizes the queue — it does not remove the human.
- The two-human ambiguity check is one sample from the space of reasonable readings; it catches gross ambiguity, not subtle ones, and it is the only gate that does not scale automatically.
- Metamorphic variants raise the cost of memorization but a model can memorize the variant family too once a pack leaks; the private eval pack mitigates this only as long as it actually stays private, which is an operational discipline, not a technical guarantee.
- The memorization probe detects only verbatim recall; paraphrastic contamination of local LLMs passes it silently. Post-cutoff sourcing helps but limits the supply of mature, realistic repos.
- Forked time series are statistically clean but operationally annoying: every pack bump resets longitudinal narratives, and stakeholders will be tempted to compare across the fork anyway. The UI must label forks loudly; the schema prevents pooling, not misreading.
