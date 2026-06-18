# AgentForge Arena — Development Log

A chronological, exhaustive record of how this project was built: every request,
the reasoning behind each decision, what was done, the resulting numbers, the
bugs found and fixed, and the answers given along the way. Newest work is added
at the bottom. This is a narrative companion to the code and the design doc —
when you want to know *why* something is the way it is, look here.

**Compiled:** 2026-06-18 (stated session date). Note: artifact timestamps in the
repo vary (git commit, file mtimes, the `~/.claude` backup dir `20260617`), so
this log is organized by **phase**, not wall-clock time.

**How to read it:** each phase is one request-and-response cycle. "Ask" = what
was requested. "Reasoning" = why I chose the approach. "Did" = the concrete
actions. "Outcome" = results/numbers. "Findings" = anything notable discovered.

---

## Test-count timeline (quick reference)

| After phase | Suite | What changed |
|---|---|---|
| Kernel built | **167** | math core (scoring, aggregation, confidence, domains, ranking) |
| v0.1 runner built | **268** | tasks, agents, sandbox, clean-room grader, store, report |
| Ollama agent hardened | **281** | real local-LLM agent + 13 offline tests |
| Task pack built | **304** | 9 new tasks + pack CI test |
| Infra-failure fix | **305** | connection errors void instead of counting as losses |
| OpenAI-compat adapter | **309** | backend-agnostic agent (LM Studio / llama.cpp / vLLM / Ollama-v1) |

All suites are pure-stdlib + pytest, fully offline.

---

## Phase 0 — The brief: design the complete evaluation framework

**Ask.** Introduced **AgentForge Arena**: an offline-first mathematical
benchmarking and observability platform for evaluating *code-modifying agents*
(MockAgent, ScriptAgent, local CLI agents, local LLMs via Ollama, optional
external APIs later). Hard constraints: **no paid LLM APIs**, **no LLM-as-judge
in core scoring**, fully offline, deterministic/statistical methods first,
useful with small data, more accurate as data grows, explainable over
black-box, implementable in FastAPI + PostgreSQL + Next.js. Requested the
*complete* mathematical and evaluation framework across 14 areas (raw run
scoring, repeated-run eval, confidence/uncertainty, domain capability, task
difficulty, ranking algorithms, multi-objective, benchmark design, eval process,
reproducibility, anti-gaming, data model, roadmap, final recommendation).

**Reasoning.** This is a design task where internal consistency matters more than
anything, so I fixed the core mathematical architecture up front (one shared
"contract" all sections obey), then fanned out authoring + verification rather
than writing 30k words linearly and hoping they cohere.

**Did.** Ran a multi-agent **Workflow (32 agents)**:
1. 10 section authors, each writing one framework section against the shared contract.
2. A numeric-verification pass that **recomputed every formula and worked example in Python**.
3. Three cross-cutting auditors: consistency, statistical-honesty red-team, implementability.
4. Fixers that applied confirmed findings.

I wrote the two anchor sections myself (`00-overview`, `11-roadmap`) to hold the
architecture and the staged plan.

**Outcome.** `docs/EVALUATION_FRAMEWORK.md` (~30,000 words) + 12 section files in
`docs/evaluation-framework/`. Audit produced **49 findings (3 critical, 27 major,
19 minor)**, all triaged/applied.

**Key architectural decisions locked in the contract:**
- **Run score:** `S = G · T_hidden · (0.85 + 0.15·Q)` — hard gates `G∈{0,1}`
  (setup, diff-exists, scope, regression, no-timeout), hidden-test fraction
  `T_hidden`, bounded quality modifier `Q` (quality can only move score within
  85–100% of itself; never substitutes for correctness).
- **Headline metric:** pass rate with a **Wilson** interval; leaderboards rank by
  the Wilson **lower bound** (LCB) — small samples penalize themselves.
- **Stability** = `max(0, 1 − 2s)`. **Retries:** unbiased `pass@k`.
- **Rejected** Elo/Glicko/TrueSkill (wrong fit for a static agent-by-task grid;
  order-dependent; patent issues). **v1.0** = hierarchical Bayesian Rasch (which
  subsumes Bradley-Terry) fit offline in PyMC.
- **Domains** = weighted tags → pooled pass rate with Kish effective-N Wilson;
  overall = macro-average, always labeled benchmark-relative, never "universal IQ."
- **Clean-room grading**, hidden tests never in the agent's sandbox, anti-gaming
  defenses, append-only raw data with recomputable derived scores.

**Findings (verification caught real errors before they shipped):** a
coverage-test assertion that would have failed ~98.5% of the time on *correct*
code; a mathematically impossible `pass@k` example; an inconsistent
point-biserial formula; a reachable divide-by-zero in the quality score.

---

## Phase 1 — "eeeeeehhhhh maybe a too much of a research?"

**Ask.** Was that too much research?

**Answer I gave.** Honestly, no — for what was asked (the complete framework over
14 areas), that *was* the deliverable. **But** I named the real risk: a
30k-word doc can become a reason *not* to build. The v0.1 slice is actually
small (a few hundred lines + a handful of tables). The danger is treating the
full framework as a prerequisite instead of a reference. Use §1 to implement
scoring and §11's v0.1 list as the feature scope.

---

## Phase 2 — "then what do you think we should do?"

**Answer I gave.** Build. The design is the map; more design now is
procrastination. Proposed the v0.1 skeleton in order: (1) a pure scoring
function, (2) MockAgent + one real task, (3) the Postgres raw schema, (4) a CLI
runner. Recommended starting with the scoring function (the mathematical core
with no dependencies).

---

## Phase 3 — "step by step but not all at once"

**Ask.** Wanted to proceed incrementally, on their signal.

**Did.** Saved a project memory file recording the v0.1 build order and design-doc
locations so context survives across sessions.

---

## Phase 4 — "what are we going to start with?"

**Answer I gave.** `score.py` — a pure Python function taking gate results + test
results + diff stats and returning `S`, `X`, and the Wilson interval. No DB, no
Docker — just the math, made testable.

---

## Phase 5 — "Implement only the v0.1 evaluation kernel first"

**Ask.** Don't design more. Build the v0.1 math kernel, executable and
unit-tested. No dashboard, Docker, or agents yet.

**Reasoning.** "v0.1 kernel" sensibly means the whole v0.1 *math stack* (scoring +
aggregation + confidence + domains + ranking), not just one function — that's the
smallest genuinely-usable slice. I wrote the shared type contract and module
stubs myself (the interface authority), then used a Workflow to fill in bodies +
tests + adversarial numeric verification.

**Did.** Created the `afa_kernel` package (`kernel/afa_kernel/`): `types.py`
(frozen dataclasses + enums), `confidence.py` (Wilson, LCB, pass@k, t-table,
stability), `scoring.py` (`score_run`), `aggregate.py` (repeated-run stats),
`domains.py` (pooled + Kish-N Wilson, macro overall), `ranking.py` (LCB ranking
with tie clustering). Workflow phases: foundation modules → dependent modules →
integration (consolidated anchor tests, drive to green) → 5 adversarial
math-verifiers → conditional fix.

**Outcome.** **167 tests pass**, pure stdlib, zero warnings. Canonical anchors all
hold: Wilson(3,5)=[0.2307, 0.8824]; pass@k(5,2,3)=0.9; the §1 worked example
S=0.6727.

**Findings (adversarial verifiers caught 2 real bugs the tests missed):**
1. **Wilson float-leak (major):** `wilson_interval(0, 26)` returned `1.39e-17`
   instead of exactly `0.0` for an all-fail agent (the clamp didn't fire at
   certain n). Fixed by snapping all-fail/all-pass endpoints exactly.
2. **Ranking self-comparison (critical):** that float leak let a zero-pass agent
   "out-rank itself," producing impossible rank ranges in ~7,500 of a 500k
   random sweep. Fixed by excluding each agent from its own out-ranking counts.

I then applied two polish fixes myself: an X/S consistency nit (an all-zero-weight
hidden suite scored S=0 yet reported a functional pass — now X requires positive
hidden weight) and silenced a pytest collection warning on the `TestResult`
dataclass.

---

## Phase 6 — "create a whole plan, and finish this off in one go"

**Ask.** Build the rest of the v0.1 vertical slice so it actually runs end to end.

**Reasoning.** Offline-first + testable-now argued for **pluggable** sandbox and
storage behind interfaces, with working defaults that need no infra:
`LocalSandbox` (subprocess + fresh temp dir, same interface Docker would
implement) and `SqliteRunStore` (stdlib `sqlite3`). The production Postgres DDL
is still delivered as the schema. I wrote the contract (interfaces, the task
content, the DDL) myself, then fanned out implementation + verification.

**Did.** Created the `afa_runner` package: `task.py` (loader), `agents.py`
(`Agent` protocol + `MockAgent`/`SequenceAgent`/`ScriptAgent`), `sandbox.py`
(`LocalSandbox`), `diffing.py` (whole-file diff + scope checks), `grader.py`
(clean-room grading via pytest JUnit XML), `pipeline.py` (`run_once`/`run_group`
+ `validate_task`), `store.py` (`SqliteRunStore`), `report.py` (leaderboard /
domain profile). Plus the first real task `tasks/fix-list-dedup/`, the Postgres
`db/schema.sql`, and `examples/run_demo.py`. Workflow: leaf modules → mid modules
→ integration (pipeline + e2e test + demo, drive to green) → 4 adversarial
dimensions (clean-room integrity, isolation/reproducibility, gate/diff
correctness, task validity) → fix.

**Outcome.** **268 tests pass.** The demo ran three agents at n=5 and produced an
honest leaderboard: a perfect "oracle" and a 3/5 "seq" agent landed in a **rank
1–2 tie** (because at n=5 a 5/5's lower bound 0.566 < a 3/5's point estimate 0.6
— the math refusing to fake separation), with the noop agent clearly last.

**Findings (adversarial review caught a CRITICAL clean-room break):** an agent
could drop a `conftest.py` / `sitecustomize.py` / `*.pth` into its workspace;
pytest would auto-execute it during grading, letting the agent monkeypatch the
function-under-test and score 1.0 *without fixing the bug*. Fixed by treating
auto-executed files as **always-protected** plus an **editable allow-list**
(`task.editable_paths`); any such injection is now a scope violation → G=0 → S=0.
I re-ran the exact attack to confirm it's blocked while a legitimate fix still
scores 1.0.

---

## Phase 7 — Freeze and commit v0.1

**Ask.** `git add . && git commit -m "Freeze v0.1 offline evaluation slice" && git tag v0.1-eval-slice`.

**Did.** Repo wasn't a git repo yet → `git init`. Caught two `.DS_Store` files
that got staged → added to `.gitignore` and unstaged. Committed.

**Outcome.** Commit **`8eb6d4a`**, **56 files, 12,021 insertions**, tag
**`v0.1-eval-slice`**.

---

## Phase 8 — "make that repo private"

**Did.** No remote existed. Created a **private** GitHub repo via `gh`, set it as
`origin`, pushed `master` + the tag. Verified visibility = PRIVATE via API.

**Outcome.** `https://github.com/thebunnyguy/agentforge-arena` (private), account
`thebunnyguy`.

---

## Phase 9 — "what's the next plan?"

**Answer I gave.** The v0.2 critical path, in order: (1) **task pack** (breadth —
the system is only as good as its task pool; the difficulty math is meaningless
with one task), (2) a **real local agent** (Ollama), (3) **DockerSandbox**, (4)
**Postgres + FastAPI**, (5) **Next.js dashboard**, (6) **v0.2 math** (Jeffreys
shrinkage, empirical difficulty, discrimination). Recommended starting with the
task pack.

---

## Phase 10 — "before starting, evaluate a real open-source coding agent"

**Reasoning.** "Real OSS agent, offline" means a locally-served open-weights model.

**Did.** Probed the machine: **Ollama installed** (not running) with `llama3.2`
+ `nomic-embed-text` pulled; **no Docker**; `transformers` present. Started
Ollama, smoke-tested `llama3.2` on the dedup task (correct fix in ~16s). Built
**`OllamaAgent`** (`agents_ollama.py`): reads the editable files, prompts the
local model over HTTP, parses fenced code blocks, writes them back. The HTTP
call is **injectable** so unit tests stay offline. Hit and fixed a parser bug
(the model emits `# FILE: path` as the *first line inside* the code block, not
before it). Evaluated `llama3.2` on dedup at **n=12**.

**Outcome.** **7/12 pass**, Wilson [0.320, 0.807], **bimodal** (every score 0 or
1 — the mean is a fiction), **pass@1=0.58 but pass@3=0.96**. Two distinct failure
modes the framework cleanly separates: 2 runs produced *no usable code*
(diff-exists gate), 3 produced a *wrong fix* (hidden tests fail). Then a
hardening Workflow added 13 offline mocked tests + adversarial confirmation that
a malicious model (editing a test file, injecting `conftest.py`, path traversal)
is caught (G=0, S=0). **281 tests.**

---

## Phase 11 — "yes evaluate a stronger one"

**Did.** Pulled **`qwen2.5-coder:7b`** (~4.7 GB, the coder-specialized model).
Wrote `eval_compare.py` and ran qwen vs llama on dedup at n=12.

**Outcome.** qwen **12/12** (Wilson [0.757, 1.000]); llama **7/12**.

**Findings.** qwen **tied the oracle at rank 1–2** — not because qwen is perfect,
but because at n=12 on an easy task the math *cannot distinguish two perfect
scorers* and correctly refuses to fake an order. This was the data telling us the
single task was too easy to separate strong agents → motivated the task pack.

---

## Phase 12 — "don't commit, let's go for the next stage now"

**Ask.** Build the task pack with a difficulty spread that can separate strong
models. Don't commit.

**Did.** Designed 9 new tasks (difficulty 2→5) across domains/activities,
authored them in parallel via Workflow, each **self-validated by `validate_task`**
(the §8 benchmark CI: reference fix scores 1.0 three times identically; the
unmodified snapshot fails hidden but passes regression). Added `tasks/manifest.json`,
a parametrized pack CI test (`runner/tests/test_task_pack.py`), and
`examples/eval_pack.py`. An adversarial audit reviewed every task.

**The pack** (all follow the "stable sibling + function-under-test" pattern):

| id | domain(s) | activity | scale | diff |
|---|---|---|---|---|
| fix-binary-search | backend | debug | XS | 2 |
| fix-roman-numerals | backend | debug | S | 3 |
| implement-lru-cache | backend, api-design | feature | S | 3 |
| merge-intervals | backend, performance | feature | S | 3 |
| fix-path-traversal | security, backend | debug | S | 4 |
| toposort | backend | feature | M | 4 |
| async-gather-bounded | async-concurrency, backend | feature | M | 4 |
| refactor-order-validation | backend, api-design | refactor | M | 4 |
| expression-evaluator | backend | feature | M | 5 |

Plus the existing `fix-list-dedup` (10 total; backend primary on 8 → displayable).

**Outcome.** **9/9 valid first pass**, **304 tests**, only **2 minor** audit
findings (both on the refactor task — an inherent limit of behaviorally testing a
refactor: the suite can't force the helpers to be *wired in*).

---

## Phase 13 — First pack evaluation (later found contaminated)

**Did.** Ran `eval_pack` (qwen vs llama, n=5/task). First attempt crashed
(`UnicodeDecodeError` reading a stale `.pyc` in a task's `reference/` dir) →
fixed the reference reader to skip bytecode and cleaned the caches. Re-ran.

**Outcome (treat as provisional — see Phase 14).** Pooled: oracle 50/50 LCB
0.929 > qwen 29/50 (0.58) LCB 0.442 > llama 9/50 (0.18) LCB 0.098 > noop 0.
Backend domain: qwen [0.48, 0.74] vs llama [0.11, 0.33] (non-overlapping). The
difficulty spread **separated qwen from the oracle** — the goal. But three tasks
were 0/5 for *both* real models (fix-path-traversal, toposort, expression-evaluator)
and got flagged for inspection.

---

## Phase 14 — "proceed the diagnoses" → caught a measurement-integrity bug

> A third-party **Freeflow** Claude Code plugin began injecting a session-start
> hook here (unrelated to the project; removed in Phase 16).

**Did.** Built `diagnose_task.py` to capture real qwen attempts on the 3 tasks.
First runs showed `files_changed=0` (no edit at all). Built `probe_parse.py` to
dump the raw model response → it revealed **`URLError: Connection refused`**:
**Ollama had died.** The diagnosis runs were invalid — the agent erred on every
call and wrote nothing, so I'd been looking at the *unmodified snapshot* failing.

**Findings (the important one).** `OllamaAgent` mapped a connection error to
`AGENT_ERROR`, which **counts as a functional failure**. So the Phase-13 0/5
numbers were **contaminated** — a dead model server was being scored as the agent
getting answers wrong. This is exactly the "never blame the agent for
infrastructure failure" principle (framework §1).

**Fix.** Added `AgentOutcome.infra_failed` → the pipeline maps it to
`INFRA_FAILURE` (**voided, excluded from n**, checked before `errored`), and
`OllamaAgent` now classifies transport errors (`URLError`, `ConnectionError`,
timeouts, `HTTPException`) as infra rather than an agent loss. Added regression
tests. **305 tests.**

---

## Phase 15 — Clean re-run (killed)

Restarted Ollama and launched a clean pack re-run; it was killed before
completing (see Phase 16 — the next request interrupted it). Established that
Ollama wasn't crashing on its own — background processes spawned inside my jobs
get reaped when those jobs end.

---

## Phase 16 — "no, remove the freeflow plugin"

**Did.** Located Freeflow (a Claude Code plugin, host-level, **not** part of this
repo) in `~/.claude/settings.json` + `plugins/installed_plugins.json` +
`plugins/known_marketplaces.json`, with cloned files in four directories. **Backed
up** the three config files to `~/.claude/backups/pre-freeflow-removal-20260617-135249/`,
removed the entries, deleted the cloned dirs, and verified all JSON valid + zero
`freeflow` references remain.

**Note.** Hooks/skills already loaded in the running session persist until a
**Claude Code restart**; after restart Freeflow is fully gone.

---

## Phase 17 — "how is the progress gone so far?"

**Answer I gave.** A phase-by-phase recap: v0.1 committed (tag `v0.1-eval-slice`);
the v0.2 work (real-agent support, task pack, infra fix) uncommitted by request;
305 tests; the headline finding that the platform distinguishes "infra hiccup"
from "agent wrong"; and the one open thread — a clean pack re-run.

---

## Phase 18 — "ollama is being a problem in the system?"

**Did.** Investigated rather than guessed. Ollama was **down** (no process), but
its log showed **clean successful serves, zero crash signatures**; system had 36
GB RAM, **85% free** (no OOM).

**Answer I gave.** Ollama itself isn't buggy. The root cause is **process
lifecycle**: background processes I spawn (`ollama serve`, the eval) get reaped
when a job ends or is interrupted. The deeper point — Ollama is the heaviest,
flakiest dependency in the loop, which is exactly why the Phase-14 infra-void fix
matters (the platform now tolerates Ollama outages instead of recording false
failures). Recommended: user starts Ollama persistently, or I bundle
serve + eval into one job.

---

## Phase 19 — "i opened it, it's very unresponsive… but you do what you do"

**Did.** Probed: connection refused *instantly* (nothing listening — the app
hadn't brought its server up). So I **bundled** `ollama serve` + a readiness wait
+ a focused eval into **one** background job (shared lifecycle = no reaping).
Wrote `eval_subset.py`, which reports valid / pass / **void** splits so a flaky
server can't corrupt the verdict. Ran qwen on the 3 suspect tasks at n=5.

**Outcome (clean — 0 voids).**

| task | valid | pass | void | verdict |
|---|---|---|---|---|
| fix-path-traversal | 5 | 1 | 0 | true rate ~20% — its 0/5 was the outage artifact |
| toposort | 5 | 0 | 0 | genuinely hard — 5 "wrong-fix" |
| expression-evaluator | 5 | 0 | 0 | genuinely hard — 5 "wrong-fix" |

**Findings.** All three tasks are **legitimately hard, not over-strict/ambiguous**:
every failure is the model producing *wrong code*, zero no-edits, zero voids. The
contamination was real but smaller than feared (only path-traversal was wrongly
0). The task pack is validated as a genuine discriminator, and the infra-void
mechanism proved it can tell an outage from a miss.

---

## Phase 20 — "idk what you're saying"

**Course-correction.** I had been too jargon-heavy. Reset to plain English:
explained that the project auto-grades AI coding assistants; that we tested two
free local AIs (qwen clearly better than llama); that a scare where the good AI
"scored zero" turned out to be the **Ollama program crashing mid-test**, not the
AI; that I fixed the tool so a crash no longer counts against the AI; and that a
clean re-run confirmed two problems are genuinely hard and one is solvable
sometimes. Offered four plain choices: Save it / Keep testing / Show me / Stop.

---

## Phase 21 — "if ollama doesn't work out, find something more efficient to test"

**Did.** Probed alternatives: **llama.cpp** not installed; **LM Studio installed**
(`lms` CLI; has `mistralai/ministral-3-14b-reasoning`, ~12 GB, already downloaded);
**transformers + torch 2.8 + Apple GPU (MPS)** available in-process; Ollama's
models still on disk. Built **`OpenAICompatAgent`** (`agents_openai.py`) — a
subclass of `OllamaAgent` that talks to **any OpenAI-compatible server**
(`/v1/chat/completions`): LM Studio, llama.cpp, vLLM, or Ollama's own `/v1`. It
reuses all parsing + the infra-failure classification; only the network call
differs. Added 4 offline tests. **309 tests.**

**Answer I gave (honest verdict).** There isn't a *faster* backend on this
machine — Ollama with qwen-7B is the most efficient (Metal GPU, models already
local) and worked perfectly when run bundled. The reliability issue was
operational, not Ollama being slow. So the real win is **no lock-in**: keep
Ollama bundled as the fast primary; the new adapter lets you point at LM Studio
(one setting) if Ollama ever frustrates you. The most *crash-proof* option is
in-process `transformers` (no server to die) but it's CPU/MPS-bound and needs a
download.

---

## Phase 22 — "do we have any .md files?"

**Answer I gave.** Listed 14 real docs: `README.md`, `kernel/README.md`,
`docs/EVALUATION_FRAMEWORK.md`, and its 12 section files in
`docs/evaluation-framework/`. (The two `.pytest_cache/README.md` files are
git-ignored auto-generated cache notes.)

---

## Phase 23 — "create a log file like .md… log every single thing"

**Did.** Created this file (`DEVLOG.md`).

---

## Phase 24 — Commit v0.2 + the clean full pack evaluation

**Ask.** Commit the changes and run one clean full pack evaluation.

**Did.** Confirmed the suite green (309), staged everything (gitignore kept all
`.DS_Store`/`__pycache__` out), and committed to master: **`49999df`**, **88
files, +4,239** — both real agents, the infra-failure fix, the 9-task pack +
manifest + CI test, the eval/diagnostic scripts, and `DEVLOG.md`. (Not pushed —
the ask was "commit," not "push.") Then ran `eval_pack` (all 10 tasks, both
models, n=5) with Ollama **bundled** into the one job and infra-voids tracked.

**Outcome (clean — 0 voids, both agents n=50):**

```
rank  agent              n   p̂     LCB
  1   oracle (reference) 50  1.000  0.929
  2   qwen2.5-coder:7b   50  0.580  0.442
  3   llama3.2           50  0.180  0.098
  4   noop               50  0.000  0.000
```

Per-task: qwen near-perfect on diff 2–3, falls off at diff 4–5; 0/5 on
fix-path-traversal, toposort, expression-evaluator. Backend domain: qwen
[0.48, 0.74] vs llama [0.11, 0.33]. qwen ≈ 3× llama, cleanly separated, both
below the perfect oracle.

**Findings.** These numbers **reproduce the Phase-13 run almost exactly**
(qwen 29/50, llama 9/50). So the earlier "contaminated" worry was an
overcorrection — the original pack run was fine; Ollama only died *later*,
during the Phase-14 diagnosis attempts. The diagnosis's real value was the code
bug it caught (Phase 14) and confirming the hard tasks are legit (Phase 19), not
rescuing these numbers. The infra-fix remains correct and necessary regardless.
The hard tasks held: toposort/expression-evaluator 0 for both; fix-path-traversal
~0–10% across runs (1/5 focused, 0/5 here — normal low-rate variance).

---

## Phase 25 — Visual reports (the observability layer, first step)

**Ask.** "What else are we supposed to do?" → chose **visual reports**; smart
scoring (v0.2 math) and more tasks/agents explicitly deferred.

**Reasoning.** The engine works; the missing half of "benchmarking *and
observability*" is a way to *see* the results. Started with the lightest useful
form — a self-contained offline HTML report — rather than standing up
Postgres + API + Next.js immediately.

**Did.** Built `runner/afa_runner/report_html.py` — `render_report(store,
tasks_meta)` produces one standalone `.html` (inline CSS + SVG, no server, no
internet, no JS deps) with a leaderboard (Wilson-interval bars), a per-task
pass-rate heatmap, per-agent cards (pass rate + no-edit/wrong-fix/voided split),
and a domain profile. Honesty rules are rendered, not just computed: intervals
shown, rank clusters, "provisional" (n<5) and "insufficient data" (domain <5
tasks) labels, voids surfaced separately. Added `examples/report_pack.py`
(reconstructs the real Phase-24 results into the report instantly — leaderboard/
matrix/domain are exact; per-run scores synthesized 1.0/0.0, faithful for these
binary tasks), 4 offline tests (`runner/tests/test_report_html.py`), exported
`render_report`, and gitignored the generated `reports/` dir. Showed an inline
preview widget in chat.

**Outcome.** **313 tests pass.** `reports/leaderboard.html` generated
(`open reports/leaderboard.html`). The renderer takes any `RunStore`, so a live
run can produce the report directly.

---

## Phase 26 — Fair 5-model comparison + the "stops" fix

**Ask.** Run more tests with different models (fair: same pack, math, n). Then:
"is it my laptop?" Then make runs survive. Then commit (no push) + update the report.

**The "stops" diagnosis.** Multiple long background runs were getting killed
mid-way. Checked the machine: 36 GB RAM / 70% free, 14 cores at ~5 load, 101 GB
disk, swap normal, and **zero** OOM/crash lines in Ollama's log. So **not the
laptop** — the background jobs were being reaped at turn boundaries / on a
duration cap by the tooling that runs them. Fixes: (1) run the eval in the
FOREGROUND within a single turn so it completes before yielding; (2) persist
every run to a SQLite file the instant it finishes (resumable — a stop costs at
most one run); (3) flush progress live. New: `examples/eval_persist.py`
(resilient, resumable, per-model) and `examples/report_combined.py` (merges
fresh DB runs with the known baselines → report). Run data lands in
`reports/runs.sqlite` (gitignored).

**Did.** Pulled 3 new models (qwen2.5-coder:3b, deepseek-coder:6.7b, gemma2:2b);
ran them fresh through the identical harness; combined with the earlier
qwen-7b/llama run (same conditions) + oracle/noop bookends.

**Outcome (5-model leaderboard, pooled n=50, ranked by Wilson LCB):**

```
1    oracle (reference)   1.000  LCB 0.929
2    qwen2.5-coder:7b     0.580  LCB 0.442
3-4  qwen2.5-coder:3b     0.280  LCB 0.175
3-5  llama3.2:3b          0.180  LCB 0.098
4-5  deepseek-coder:6.7b  0.160  LCB 0.083
6    gemma2:2b            0.040  LCB 0.011
7    noop                 0.000  LCB 0.000
```

**Findings.** (1) **Bigger ≠ better:** deepseek-coder:6.7b scored *below* the
smaller qwen2.5-coder:3b — newer/better training beats raw size, and the
benchmark caught it. (2) An honest **tie cluster** at ranks 3–5 (qwen-3b / llama
/ deepseek overlap; the math refuses to fake-separate them). (3) `toposort` and
`expression-evaluator` are 0/5 for *every* model — genuinely hard. (4) The 3 new
models are fresh real runs; qwen-7b/llama reused from the identical earlier run.
`reports/leaderboard.html` regenerated with all five.

---

## Current state (as of this entry)

**Committed:**
- `8eb6d4a` (tag `v0.1-eval-slice`): the v0.1 slice — `afa_kernel`, `afa_runner`,
  the first task, `db/schema.sql`, all docs.
- `49999df`: the v0.2 batch — both real agents, the infra-failure fix, the 9-task
  pack + manifest + CI test, the eval/diagnostic scripts, `DEVLOG.md`.
- `c4adac3`: the visual report feature (`report_html.py` + `report_pack.py`
  + tests) and DEVLOG Phases 24–25.
- *this commit*: the resilient runner (`eval_persist.py`), the 5-model combined
  report (`report_combined.py`), and DEVLOG Phase 26.

**Uncommitted:** none after this commit.

**Repo:** private GitHub `thebunnyguy/agentforge-arena`. Local master is **3
commits ahead of `origin`** (v0.1 is pushed; everything since is committed but
**not pushed**, by request).
**Suite:** 313 passing, offline, pure stdlib.

**Open threads:**
1. ~~Clean full pack re-run~~ — **done** (Phase 24; reproduced the earlier numbers, 0 voids).
2. ~~Commit the v0.2 work~~ — **done**; **not yet pushed** to GitHub.
3. The visual report is a static HTML file; the fuller observability layer
   (Postgres + FastAPI + Next.js dashboard) is still ahead.
4. Future v0.2 math: Jeffreys shrinkage, empirical difficulty, discrimination.

---

## Consolidated: bugs found & fixed

| # | Severity | Where | Bug | Fix |
|---|---|---|---|---|
| 1 | critical | framework verification | coverage-test assertion would fail ~98.5% of the time on correct code | corrected the assertion |
| 2 | — | framework | impossible `pass@k` example; inconsistent point-biserial; reachable divide-by-zero in Q | corrected all three |
| 3 | major | kernel `confidence` | `wilson_interval(0,26)` → `1.39e-17` not `0.0` | snap all-fail/all-pass endpoints |
| 4 | critical | kernel `ranking` | agent could "out-rank itself" → impossible rank ranges | exclude self from out-ranking counts |
| 5 | minor | kernel `scoring` | all-zero-weight hidden suite → X=True but S=0 | X requires `t_hidden > 0` |
| 6 | **critical** | runner clean-room | agent injects `conftest.py`/`*.pth` to run code in the grader | always-protected files + editable allow-list |
| 7 | bug | `OllamaAgent` parser | model puts `# FILE:` inside the code block | detect in-block path marker |
| 8 | **integrity** | `OllamaAgent`/pipeline | connection errors scored as agent failures (contaminated an eval) | `infra_failed` → `INFRA_FAILURE` (voided) |
| 9 | bug | `eval_pack` | crashed reading a stale `.pyc` in `reference/` | skip bytecode in the reference reader |

---

## Consolidated: process notes

- **Workflows** (multi-agent fan-out + adversarial verification) were used for the
  big builds: the framework (32 agents), the kernel, the v0.1 runner, the Ollama
  hardening, and the task pack. The recurring pattern — *author → numerically
  verify → adversarially red-team → fix* — caught every critical bug above.
- **The interface contract was always written by hand** before fanning out, so
  parallel agents couldn't diverge on shared types/signatures.
- **Honesty rules that earned their keep:** ranking by lower bound (refuses fake
  separation at small n); voiding infra failures (refuses to blame the agent for a
  dead server); bimodality flagging (refuses to report a fictional mean); the §8
  benchmark CI (every task provably well-formed before it counts).
- **Ollama operational lesson:** start it *bundled* with the eval (one job:
  `serve → wait ready → run`), or run it as a persistent app outside the
  automation. Don't start it in a throwaway subshell.
