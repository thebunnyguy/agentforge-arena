# AgentForge Arena

**Evidence-first evaluation and benchmark validation for AI agents.**

AgentForge is a local-first evaluation laboratory for code-modifying agents. It is built to answer a harder question than:

> **What score did this model get?**

It is designed to answer:

> **Can I trust the evidence behind this result?**

AgentForge runs agents against versioned tasks, preserves exact run evidence, validates the benchmark itself, separates current and historical results, and publishes reproducible benchmark releases with explicit uncertainty and limitations.

The core grading path is deterministic and does **not** require an LLM judge.

---

## Current status

**Phase 0 is complete.**

- Runtime release: **phase0-integrity-v1**
- Official benchmark release: **phase0-modern-local-v1**
- 24 versioned coding tasks
- 5 overlapping benchmark domains
- 600 fresh real runs in the latest official benchmark
- 5 modern local models
- 5 repetitions per model/task cell
- Local Ollama inference for the official campaign
- No paid API used for Modern Local Benchmark v1

AgentForge currently focuses on **code-modifying agents**. Broader state-changing workflows are future work, not a claimed current capability.

---

# Quickstart

## Prerequisites

You need:

- **Python 3.10+**
- **Node.js 18+** and npm
- Git
- Optional: **Ollama** or another local OpenAI-compatible model server if you want to run real-model evaluations

You do **not** need a model installed just to browse the included benchmark releases and historical evidence.

## 1. Clone the repository

~~~bash
git clone https://github.com/thebunnyguy/agentforge-arena.git
cd agentforge-arena
~~~

## 2. Create a Python virtual environment

### macOS / Linux

~~~bash
python3 -m venv .venv
source .venv/bin/activate
~~~

### Windows PowerShell

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
~~~

## 3. Install the local app dependencies

The repository is currently run directly from its source tree rather than installed as a packaged Python distribution.

~~~bash
python3 -m pip install --upgrade pip
python3 -m pip install   "fastapi>=0.110"   "uvicorn[standard]>=0.27"   "httpx>=0.27"   "pydantic>=2.6"
~~~

For Python tests, also install pytest:

~~~bash
python3 -m pip install "pytest>=7.0"
~~~

## 4. Start AgentForge

~~~bash
python3 afa_app.py
~~~

On macOS, you can also double-click:

**start.command**

The launcher will:

1. create a writable working database if needed,
2. install frontend dependencies on the first run,
3. build the React frontend,
4. start the API,
5. start the evaluation worker,
6. open your browser.

Open manually at:

**http://localhost:8000**

Press **Ctrl-C** to stop AgentForge.

---

# Browse results without installing a model

A local model is not required to inspect the published evidence.

Start the app:

~~~bash
python3 afa_app.py
~~~

Useful pages:

| Page | Purpose |
|---|---|
| **/benchmarks** | Frozen benchmark releases |
| **/leaderboard** | Current working-database leaderboard |
| **/tasks** | Task/version inspection |
| **/agents** | Model/agent evidence |
| **/reports** | Reports and exports |

The **Benchmark Releases** pages are the authoritative place to inspect the frozen Modern Local Benchmark v1 result.

The live leaderboard is a projection over the app's working database and should not be confused with the frozen benchmark release.

---

# Run your first real evaluation

AgentForge supports:

- Ollama
- local OpenAI-compatible servers such as LM Studio, llama.cpp and vLLM

## Ollama example

Install Ollama, then pull a model. A smaller model such as Qwen 3.5 9B is a practical first test:

~~~bash
ollama pull qwen3.5:9b
~~~

Make sure Ollama is running:

~~~bash
ollama serve
~~~

Then start AgentForge:

~~~bash
python3 afa_app.py
~~~

Open **New Evaluation** in the app, choose the local backend, select a model, choose tasks and repetitions, and start the evaluation.

Each evaluation receives its own durable evaluation ID and produces evaluation-scoped results.

---

# Evaluation lifecycle

AgentForge distinguishes three execution modes.

## Fresh

Fresh execution is the default.

Running the same model/task configuration again produces new raw evidence rather than silently reusing an older run.

## Resume

A failed or canceled evaluation can continue under the **same evaluation ID** when compatible unfinished trials remain.

Completed trials stay completed. Only unfinished positions continue.

## Reuse

Evidence reuse is explicit.

Compatible evidence can be linked into another evaluation while remaining clearly marked as reused. Reused evidence is never presented as freshly executed evidence.

---

# Evaluation reports

Each evaluation exposes deterministic, evaluation-scoped reports:

~~~text
GET /api/v1/jobs/{evaluation_id}/report.json
GET /api/v1/jobs/{evaluation_id}/report.md
~~~

The results page provides:

- **Report JSON**
- **Report Markdown**

Reports are scoped to one evaluation rather than the global leaderboard.

They include persisted trial outcomes, exact run identity, task snapshots, provenance and limitations.

---

# Configuration

The native launcher has working defaults.

Common environment variables:

| Variable | Purpose | Default |
|---|---|---|
| **AFA_HOST** | Local bind address | 127.0.0.1 |
| **AFA_PORT** | Local app port | 8000 |
| **AFA_DB_PATH** | Writable working database | reports/app.sqlite |
| **AFA_OLLAMA_BASE_URL** | Local model endpoint | local Ollama |
| **AFA_NO_BROWSER** | Disable automatic browser opening | unset |

Example:

~~~bash
AFA_PORT=8010 python3 afa_app.py
~~~

The committed evidence database is not used as the writable runtime database.

---

# Docker

Docker Compose is an alternative way to run the local app.

~~~bash
docker compose up --build
~~~

Open:

**http://localhost:8080**

By default, the containers connect to Ollama running on the host.

To run Ollama through Compose as well:

~~~bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile ollama up --build
~~~

The published ports bind to localhost.

> Docker packaging does not turn AgentForge into a hardened sandbox. It remains a trusted, single-user local tool.

The official Modern Local Benchmark v1 campaign was frozen separately from ordinary app usage.

---

# Tests

## Python

From the repository root:

~~~bash
python3 -m pytest
~~~

The project test configuration includes the kernel, runner, API, integration, benchmark-integrity and campaign test suites.

## Frontend

~~~bash
cd web
npm install

npm run typecheck
npm run build
npm run test:focused
~~~

Additional browser suites:

~~~bash
npm run test:browser
npm run test:async
npm run test:benchmarks
npm run test:real
~~~

The real-app suite may skip the optional local Ollama smoke when Ollama is unavailable.

## Verify benchmark-release data

~~~bash
PYTHONPATH=campaigns python3 -m afa_campaign release-data --check
~~~

This checks the generated benchmark-release datasets against their committed source evidence.

---

# Modern Local Benchmark v1

The first official post-Phase-0 benchmark release evaluates five locally runnable models through the same AgentForge coding protocol.

## Environment

- Apple M4 Max
- 36 GiB unified memory
- Ollama 0.31.1
- 24 tasks
- 5 repetitions per task
- 120 runs per model
- 600 total accepted real runs
- Temperature 0.8
- Seeds 42–46
- 180-second request timeout
- $0 paid API cost

## Official leaderboard

Ranking uses AgentForge's Wilson 95% lower-confidence-bound ordering.

| Rank | Model | Passes | Pass rate | Wilson 95% | Timeouts |
|---:|---|---:|---:|---:|---:|
| 1 | gpt-oss:20b | 96 / 120 | **80.0%** | 72.0–86.2% | 0 |
| 2 | devstral-small-2:24b | 71 / 120 | **59.2%** | 50.2–67.5% | 5 |
| 3 | qwen3.5:9b | 40 / 120 | **33.3%** | 25.5–42.2% | 30 |
| 4 | qwen3-coder:30b | 18 / 120 | **15.0%** | 9.7–22.5% | 0 |
| 5 | qwen3.6:27b | 11 / 120 | **9.2%** | 5.2–15.7% | 105 |

Every ranked model completed all 24 tasks with five repetitions per task.

## Important interpretation notes

### Qwen3-Coder 30B-A3B — protocol sensitivity

96 of 120 runs produced no applied edit.

In a diagnosed reproduction, the model generated a correct code change but omitted the opening fenced-code delimiter required by AgentForge v1, so the edit parser did not apply the change.

The campaign does not retain every raw response, so that specific cause is not established for all 96 no-edit runs.

The result therefore reflects both task performance **and compliance with AgentForge v1's output protocol**. It should not be read as a general statement about the model's underlying coding ability.

### Qwen3.6 27B — latency constrained

105 of 120 runs were timeout-classified, including 83 full 180-second request timeouts.

This result describes Qwen3.6 under the fixed AgentForge local latency budget on this hardware. It is not a general capability conclusion.

---

# Why trust the result?

Modern Local v1 is not simply a leaderboard generated from whatever rows happened to exist in a database.

The campaign validator verified:

~~~text
600 / 600 accepted real runs
0 missing runs
0 extra campaign runs
0 synthetic benchmark runs
0 provenance conflicts
0 legacy runs in the campaign cohort

24 / 24 current task versions
24 / 24 pinned task digests
5 / 5 pinned model identities
120 / 120 model-task cells at the expected model digest
~~~

The benchmark result is frozen under:

**phase0-modern-local-v1**

The evaluation runtime used to generate it is frozen separately under:

**phase0-integrity-v1**

This keeps the benchmark result independent from later presentation/UI changes.

See:

- [Modern Local Benchmark v1 campaign](docs/campaigns/PHASE0_MODERN_LOCAL_CAMPAIGN.md)
- [Modern Local Benchmark v1 promotion](docs/release/PHASE0_MODERN_LOCAL_PROMOTION.md)
- [Frozen result artifacts](campaigns/phase0-modern-local-v1/results/)

---

# Two layers of integrity

AgentForge treats the **evaluation** and the **benchmark judging that evaluation** as separate systems that can both fail.

## Evaluation integrity

Each evaluation has a durable identity.

AgentForge tracks:

- evaluation ID
- task/repeat trial identity
- exact raw run ID
- model/backend configuration
- task version
- task content digest
- generation parameters
- evidence provenance
- fresh vs reused evidence
- source/origin relationships
- persisted patches
- test results
- evaluation-scoped reports

## Benchmark integrity

AgentForge also checks whether the benchmark itself deserves to be trusted.

The integrity system evaluates:

- reference solution validity
- no-op/unmodified behavior
- known-bad controls
- alternative controls
- semantic mutations
- generic AST mutations
- protected-path behavior
- import-closure issues
- repeated-grading determinism
- task/version provenance

Current 24-task pack audit:

| Status | Tasks |
|---|---:|
| **HEALTHY** | 15 |
| **NEEDS_REVIEW** | 2 |
| **PROVISIONAL** | 7 |
| **INVALID** | 0 |

AgentForge does not force every task to appear healthy merely to make the benchmark look cleaner.

See [Benchmark integrity](docs/BENCHMARK_INTEGRITY.md).

---

# Evidence, not just scores

A benchmark number should be traceable back to what happened.

For a persisted run, AgentForge can connect:

~~~text
evaluation
    ↓
trial
    ↓
exact runs.id
    ↓
patch
    ↓
regression tests
    ↓
hidden tests
    ↓
score primitives
    ↓
functional outcome
~~~

Exact run identity matters once the same model has been evaluated multiple times. The live UI resolves evaluation-scoped trial links through their persisted run IDs rather than relying only on model + task + repetition.

---

# Current vs historical evidence

Benchmark definitions change.

AgentForge does not silently treat evidence from an older task version as evidence for a newer one.

For each task, the system distinguishes:

~~~text
CURRENT
evidence matching the current task version

HISTORICAL
evidence from an older task version

MISSING CURRENT
historical evidence exists, but the current benchmark has not been evaluated
~~~

Old evidence remains inspectable. It is simply not promoted into the current benchmark.

---

# Domain evidence

AgentForge currently groups tasks across five overlapping domains:

- backend
- api-design
- async-concurrency
- performance
- security

Normal domain display requires:

~~~text
at least 5 tasks
and
at least 25 runs
~~~

Below that threshold, real observed current evidence is still shown as **PROVISIONAL**, including its sample size and Wilson interval.

A provisional value is not treated as a fully supported domain comparison.

A domain with zero current runs is shown as **no current evidence**, not as 0%.

---

# Benchmark releases

Open:

**/benchmarks**

to inspect published benchmark releases.

Modern Local v1 includes:

- official leaderboard
- Wilson confidence intervals
- timeout counts
- model identity and quantization
- per-domain profiles
- 24 × 5 task/model matrix
- model-specific caveats
- benchmark integrity panel
- methodology and provenance
- links to frozen evidence artifacts

Benchmark-release data is generated from committed evidence rather than manually entered into the frontend.

~~~text
campaign evidence
      ↓
release definition
      ↓
consistency checks
      ↓
normalized web dataset
      ↓
benchmark UI
~~~

If the frozen evidence and generated dataset disagree, the release-data check fails.

See [Benchmark Releases UI](docs/benchmarks/BENCHMARK_RELEASES_UI.md).

---

# Historical evidence

AgentForge preserves the original pre-Phase-0 evidence database:

**reports/runs.sqlite**

It contains the earlier:

~~~text
6 models
24 tasks
5 repetitions
720 historical runs
~~~

These runs are a historical record, not the current official benchmark.

They are not directly comparable with Modern Local v1 because:

- 18 of the 24 task definitions changed
- the older runs predate the current evaluation-integrity system
- task digests were not recorded
- backend provenance was not uniformly recorded
- generation settings were not uniformly captured

The benchmark UI therefore presents that release as historical and non-comparable rather than manufacturing modern provenance or statistics that were never recorded.

---

# How one coding evaluation works

~~~text
fresh task workspace
        ↓
agent generates an edit
        ↓
capture diff
        ↓
scope / protected-path checks
        ↓
apply only that diff to a clean task snapshot
        ↓
regression tests
        ↓
hidden tests
        ↓
persist patch + grading evidence
        ↓
score run
        ↓
aggregate repeated trials
        ↓
confidence-aware result
~~~

The scoring core separates continuous diagnostic quality from functional correctness.

~~~text
S = G × T_hidden × (0.85 + 0.15Q)
~~~

A superficially good solution cannot compensate for failing required correctness gates.

See [Evaluation framework](docs/EVALUATION_FRAMEWORK.md).

---

# Repository layout

~~~text
kernel/afa_kernel/
    scoring, aggregation, confidence and ranking

runner/afa_runner/
    task execution, grading, agents and evidence storage

integrity/afa_integrity/
    benchmark auditing, controls and mutation testing

afa_api/
    FastAPI application, evaluation lifecycle and worker

web/
    React/Vite application

tasks/
    versioned 24-task benchmark pack

campaigns/
    reproducible benchmark campaign tooling and releases

reports/
    historical evidence and generated reports

docs/
    methodology, integrity, release and design documentation

afa_app.py
    one-command local application launcher
~~~

---

# Current boundaries

AgentForge intentionally makes its limitations explicit.

## Coding-specific today

The current authoritative task pack evaluates code-modifying agents.

AgentForge does not currently claim to be a universal evaluator for browser agents, research agents, memory systems or arbitrary enterprise workflows.

## Trusted local execution

The runtime is designed for a trusted, single-user local environment.

It is **not a hardened sandbox for executing malicious or untrusted agent code**.

## Hidden-test isolation

Hidden-test readability is currently classified as:

**UNVERIFIABLE**

under the trusted local sandbox.

AgentForge therefore makes no hardened hidden-test isolation claim.

## Twenty-four tasks are not the software-engineering population

Repeated trials estimate behavior on this fixed benchmark.

They should not be interpreted as proving the same success rate across all possible software-engineering tasks.

## Confidence intervals have a specific scope

The reported Wilson intervals describe repeated binary outcomes under the tested benchmark conditions.

They are not a certification of general reliability.

---

# Design principles

### Evidence before confidence

If a claim cannot be supported by the captured evidence, it should be marked incomplete or unverifiable rather than silently treated as true.

### Historical evidence stays historical

Old results are preserved rather than rewritten.

### Benchmark changes change the meaning of results

Task and grader revisions are versioned.

### Synthetic evidence is not real benchmark evidence

Mock runs remain useful for tests and canaries but are excluded from official real-model results.

### Low scores are not automatically model failures

Timeouts, protocol incompatibility, infrastructure failure and grading behavior are kept distinct where the captured evidence supports that distinction.

### The benchmark itself must be tested

A hidden test suite is not automatically correct simply because it is hidden.

---

# Troubleshooting

## ModuleNotFoundError for FastAPI, Uvicorn, httpx or Pydantic

Activate the virtual environment and install the runtime dependencies:

~~~bash
python3 -m pip install   "fastapi>=0.110"   "uvicorn[standard]>=0.27"   "httpx>=0.27"   "pydantic>=2.6"
~~~

## npm not found

Install Node.js 18 or newer.

## The app opens but no local models are available

Check Ollama:

~~~bash
ollama list
~~~

Then verify that the local Ollama server is reachable:

~~~bash
curl http://127.0.0.1:11434/api/tags
~~~

## Port 8000 is already in use

Choose another port:

~~~bash
AFA_PORT=8010 python3 afa_app.py
~~~

## I only want to inspect benchmark results

You do not need Ollama or any benchmark model installed.

Start the app normally:

~~~bash
python3 afa_app.py
~~~

and open **/benchmarks**.

## Where are my new evaluations stored?

By default:

**reports/app.sqlite**

The committed evidence database is not modified by ordinary local app usage.

---

# Documentation

Start here:

- [Evaluation framework](docs/EVALUATION_FRAMEWORK.md)
- [Benchmark integrity](docs/BENCHMARK_INTEGRITY.md)
- [Modern Local Benchmark v1 campaign](docs/campaigns/PHASE0_MODERN_LOCAL_CAMPAIGN.md)
- [Benchmark Releases UI](docs/benchmarks/BENCHMARK_RELEASES_UI.md)
- [Phase-0 closeout](docs/release/PHASE0_CLOSEOUT.md)
- [Product app design](docs/PRODUCT_APP_DESIGN.md)
- [Observability frontend design](docs/OBSERVABILITY_FRONTEND_DESIGN.md)

---

# What comes next

Phase 0 established the evaluation and evidence foundation.

Future work should build on that foundation rather than turn AgentForge into another general agent framework.

The next research direction is expected to focus on stronger **release comparisons**:

~~~text
Agent / configuration A
            vs
Agent / configuration B
            ↓
what improved?
what regressed?
what is unchanged?
what is inconclusive?
what evidence is no longer valid?
~~~

Longer term, AgentForge can expand carefully toward state-changing workflows where correctness, permissions, recovery and side effects can be independently verified.

The goal is not to evaluate every possible agent.

The goal is to make agent-evaluation claims:

**inspectable, reproducible, version-aware, and appropriately limited by the evidence.**
