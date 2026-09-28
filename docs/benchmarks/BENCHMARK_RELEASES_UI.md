# Benchmark Releases UI

The **Benchmarks** section of the web app (`/benchmarks`) presents *published benchmark releases*: frozen results
of a completed campaign (or the read-only historical record), with their uncertainty, operational behaviour,
caveats, integrity facts and a path back to the evidence that produced every number. It is presentation only —
it never recomputes a score, interval or rank and never talks to the live API for its data.

## 1. Architecture

```text
frozen campaign artifacts            release definition                 web dataset                     UI
campaigns/<campaign>/manifest.json   campaigns/releases/<id>.json       web/src/data/benchmark-         /benchmarks
campaigns/<campaign>/results/**  ─┐  (editorial facts no artifact  ─┐   releases/<id>.json          ─┐  /benchmarks/:releaseId
integrity/pack-audit/...          ├─ carries, each with a source)   ├─► (normalized, deterministic)  ├─► /benchmarks/:releaseId/models/:modelId
reports/runs.sqlite (historical) ─┘                                 │   + index.ts (registry)        │   /benchmarks/:releaseId/methodology
                                   python3 -m afa_campaign release-data   (cross-checks; fails loudly)
```

* **Generator** — `campaigns/afa_campaign/release_data.py`, run as
  `PYTHONPATH=campaigns python3 -m afa_campaign release-data` (writes) or `… release-data --check` (fails when a
  committed dataset differs from what its sources produce). It reads the evidence and writes only
  `web/src/data/benchmark-releases/<id>.json`. The output is deterministic (no timestamp of its own; every input
  file is listed under `sources` with its sha256), so `--check` compares bytes. It reads the working-tree evidence;
  `campaigns/tests/test_release_data.py` asserts that every source (apart from the definition itself) and every
  evidence link is byte-identical / present at the release's git ref (`phase0-modern-local-v1`).
* **Release definitions** — `campaigns/releases/<id>.json`: id, title, status, release date, the git ref that
  freezes the evidence, and the facts the machine-readable artifacts do not carry — each with its `source`:
  hardware, the `$0 paid API cost` statement, the ranking-method sentence, documented counts (e.g. Qwen3-Coder's
  96 no-edit runs), caveat wording, the integrity properties that are *not* claimed, and evidence links.
* **Registry** — `web/src/data/benchmark-releases/index.ts` imports each dataset, validates it once with
  `asBenchmarkRelease` (JSON imports widen every literal, so the data is checked, not cast) and exports
  `benchmarkReleases` and `defaultRelease`.
* **Contract** — `web/src/lib/benchmarkReleases.ts`: the TypeScript schema, the runtime validator and pure
  helpers (`selectDefaultRelease`, `orderReleases`, `findRelease`, `findModel`, `caveatsFor`, `evidenceUrl`,
  route builders, status descriptions). It has no side effects, so the logic tests load it under Node.

## 2. The release data model

```text
BenchmarkRelease
├── schema_version, id, title, short_title, status, released_at, summary
├── repository {url, ref, commit}            git ref that freezes the evidence (evidence links point at it)
├── campaign_id, ranked, comparable, comparability?
├── counts {models, models_ranked, tasks, repetitions, evaluations, runs, runs_per_model}
├── headline {inference, paid_api_cost{text, source}}          campaign releases
├── environment {scope, hardware{chip, architecture, memory, os, source}, hosted_api, ollama_version, backend}
├── methodology  campaign: temperature, seeds, seed policy, request timeout, repetitions, mode, runtime release,
│                evaluation granularity, evidence scope, official rule, ranking method, manifest/ledger hashes
│                historical: scoring formula, documented generation groups, not-recorded list, run window
├── integrity    campaign: accepted/planned runs and evaluations, models complete, coverage, missing, extra,
│                untracked, disowned, superseded, voided, evidence classes, backend, task pins, model identity,
│                runtime code checks, historical evidence unchanged, not_claimed[]; historical: null
├── domains[]
├── task_pack[] {task_id, task_version, task_digest, domains[{domain, weight}], activity, timeout_s,
│                version_changed_since_pre_phase0, current_version?}
├── models[]    (campaign: the official leaderboard order; historical: alphabetical by tag, not a ranking)
│   ├── id (Ollama tag), display_name, phase, optional, state, ranked, rank {low, high, provisional}
│   ├── identity {ollama_tag, digest, family, parameter_size, quantization, format, download_bytes,
│   │             context_length, digest_verified_cells, ollama_version}
│   ├── totals {runs, passes, pass_rate, wilson_low, wilson_high, mean_final_score, timeouts,
│   │           request_timeout_hits, agent_errors, voided}
│   ├── coverage, run_window, tooling_heads, receipt
│   ├── domains[] {domain, pooled_pass_rate, wilson_low, wilson_high, n_eff, n_tasks, n_runs, stability, displayable}
│   ├── tasks[] {task_id, task_version, runs, passes, pass_rate, wilson_low, wilson_high, mean_final_score,
│   │            timeouts, request_timeout_hits, agent_errors, voided, provisional, evaluation_id}
│   ├── caveat_ids[], documented_facts[]
├── caveats[] {id, model|null, kind, label, summary, points[], source, verified_fields[], documented_fact}
├── evidence_links[] {label, path, kind, model?}
└── sources[] {path, sha256}
```

**Where each number comes from** (campaign releases; the generator cross-checks every duplicated copy and refuses
the release on any disagreement):

| Field | Source |
|---|---|
| rank | leaderboard row `rank_low` / `rank_high` (the kernel's ranking by Wilson 95 % lower bound) — never list order |
| passes | model receipt `totals.passed` = completeness `per_model.passed` = Σ task-matrix `n_pass` |
| runs, pass rate, Wilson interval | leaderboard row = receipt `aggregate` = receipt `kernel_leaderboard_entry` |
| timeouts, full-request timeouts, agent errors, voided | leaderboard row = receipt `totals` |
| mean final score | receipt `aggregate.mean_final_score` |
| model × task cell | task-matrix `aggregate` (passes, runs, rate, Wilson, mean) + receipt cell (timeouts, full-request timeouts, evaluation) = completeness cell |
| domain profile | leaderboard `domain_profiles` (kernel pooled rate, Kish `n_eff`, Wilson, displayability) |
| digest / family / size / quantization | manifest roster = receipt expected and observed identity = per-cell digests at submission and acceptance |
| task version / digest | manifest = task matrix = provenance = every receipt cell |
| integrity counts | completeness receipt (`present`, `expected`, `missing`, `extra`, `evidence_classes`, `voided_positions`) and leaderboard provenance (superseded entries, launches' code checks, historical hashes) |

The generator also refuses a release when:

* a committed result file no longer matches `results/SHA256SUMS`;
* the leaderboard is not OFFICIAL, or the completeness receipt is not complete with no problems;
* any synthetic, legacy or conflicting evidence is present;
* a served rate is not its own counts' ratio (per cell and per model) or lies outside its own Wilson interval (per
  cell, per model, per domain), a rank lies outside 1..N, or the leaderboard rows are not in non-increasing
  Wilson-lower-bound and non-decreasing rank order (checked, never re-sorted or recomputed);
* a caveat's `checks` value (e.g. Qwen3.6's 105 timeouts / 83 full-request timeouts) disagrees with the evidence,
  or the caveat's text does not state that number (and, for a caveat citing a documented fact, its "96 of 120");
* the status and the source kind disagree (`HISTORICAL` ⇔ `historical-db`; `OFFICIAL` only for a ranked campaign
  release with an OFFICIAL leaderboard), `released_at` is not an ISO date (for a historical release: not the date
  of its last recorded run), or the definition lacks its git repository, tag or commit;
* a definition file is not valid JSON, or the definition or evidence lacks a required key (a `refused: …`
  message, not a traceback);
* in any full run: a dataset has no definition; with `--release`: an id is unknown; with `--check`: a dataset
  differs from what its sources produce.

**Documented, not machine-verified.** Some displayed facts exist only in the campaign report, because the campaign
database and ledger are not committed: the hardware (Apple M4 Max, arm64, 36 GiB, macOS 27.0), `$0 paid API cost`,
and Qwen3-Coder's 96 runs with no applied edit. They live in the release definition with their source. On the
release page the hardware and `$0` chips carry a *documented* marker linking to the methodology page, which shows each
source; the 96 no-edit count carries a *documented* badge on the model page.

## 3. Official, historical and other statuses

| Status | Meaning in the UI |
|---|---|
| `OFFICIAL` | Frozen, validated, campaign-owned evidence; ranked by the kernel; the default release is the newest OFFICIAL one (by `released_at`) |
| `EXPERIMENTAL` | Published for inspection; never the default while an OFFICIAL release exists. The campaign builder still requires an OFFICIAL leaderboard, so EXPERIMENTAL is an editorial status for such a campaign that is not yet promoted |
| `SUPERSEDED` | Replaced by a newer release; its numbers are kept unchanged |
| `HISTORICAL` | Recorded before the evaluation-integrity system; unranked, counts only, not comparable |

**Modern Local v1** (`phase0-modern-local-v1`, OFFICIAL) is generated from `campaigns/phase0-modern-local-v1/`
at tag `phase0-modern-local-v1`.

**Pre-Phase-0 (legacy)** (`historical-pre-phase0`, HISTORICAL) is generated from `reports/runs.sqlite`, opened
read-only and immutable only after its sha256 matches the recorded `42b6dad8…`. It shows only what that database
holds — per-model and per-cell pass counts, timeouts, the mean final score under scoring formula v0.1, the recorded
task versions (18 of 24 superseded) and the run window, models listed alphabetically by tag (the record is not
ranked) — with generation settings only where they are documented
(`campaigns/phase0-post-integrity/manifest.json`). It has **no** ranks, intervals, full digests (the two short
prefixes documented in the README are shown as such), backend provenance or hardware, and carries the statement *"Historical results are not directly comparable with Modern Local v1. Eighteen
of the 24 task definitions changed and the historical runs predate the current evaluation-integrity system."* In the
app's own vocabulary "historical" also means a single task version older than the current one; the release is
therefore titled "Pre-Phase-0 (legacy)".

## 4. Adding a future release

1. Finish and freeze the campaign (its results committed with `SHA256SUMS`, tagged).
2. Write `campaigns/releases/<new-id>.json` (copy an existing definition): id, title, status, date, git ref, the
   documented facts with sources, caveats (with `checks` for every number the evidence can verify) and links.
3. `PYTHONPATH=campaigns python3 -m afa_campaign release-data` — writes `web/src/data/benchmark-releases/<new-id>.json`
   or refuses (`refused: …`, exit 3), naming every problem it found.
4. Register it: import the JSON in `web/src/data/benchmark-releases/index.ts` and add it to the list (`--check`
   refuses a dataset that has no definition; the logic spec checks every dataset file is registered).
5. Mark an older release `SUPERSEDED` in its definition if appropriate, regenerate, and run the tests below. The
   page picks the newest OFFICIAL release automatically; no component changes.

A release from a different source kind (for example a hosted-API campaign) adds one builder to `BUILDERS` in
`release_data.py`. The schema already allows absent statistics and an absent environment, but the UI contract still
assumes local Ollama models (`identity.ollama_tag`, `environment.hardware`, `ollama_version`); those fields and their
labels must become optional before a hosted release can be rendered.

## 5. UI routes and components

| Route | Page | Shows |
|---|---|---|
| `/benchmarks` | `BenchmarkRelease` | the default release (newest OFFICIAL by metadata) |
| `/benchmarks/:releaseId` | `BenchmarkRelease` | release selector; headline (runs, evaluations, models, tasks, repetitions, inference, hardware, cost — the last two marked *documented*); local-scope notice; release-level caveats; official leaderboard (rank from the data, passes, pass rate beside its Wilson 95 % interval, coverage, timeouts with full-request timeouts, agent errors; stacked cards at ≤ 780 px) or, for a historical release, the unranked recorded table; *Reading these results* (every model caveat with its points and source); domain comparison (model × domain table with each rate's interval, plus one model's profile); 24 × N task matrix (one tab stop, arrow keys, an inline detail row under the selected task and a live summary); *Benchmark integrity* (only facts the evidence carries, then *Not claimed*); evidence links pinned to the release's git ref, the dataset path and its hashed sources |
| `/benchmarks/:releaseId/models/:modelId` | `BenchmarkModel` | status badge; model caveats; overall metrics; documented facts; identity (tag, digest, family, parameters, quantization, format, download size, context length, Ollama version, pinned-digest cells, receipt, run window, tooling head); domain profile; all task results; model switcher |
| `/benchmarks/:releaseId/methodology` | `BenchmarkMethodology` | release, runtime release, environment (with sources), generation, evaluation identity and evidence scope, model identity, task pack, hashes, dataset sources; historical: scoring formula, documented generation groups, what was not recorded |

The pages live in `web/src/pages/Benchmark*.tsx` and are lazy-loaded (`React.lazy`), so the release data ships in its
own chunk and the other pages do not carry it; `web/src/components/benchmarks/BenchmarkRoute.tsx` wraps them in a
loading state and an error boundary (a dataset that fails validation shows an error panel, not a blank app).
Components in `web/src/components/benchmarks/`: `ReleaseSelector` (links, `aria-current`), `ReleaseHeadline`,
`ReleaseResults` (ranked table + mobile cards, or the unranked recorded table; model identities), `ReadingResults`,
`DomainComparison` / `DomainProfile`, `TaskMatrix`, `IntegrityPanel`, `EvidencePanel` / `DatasetSources`, and
`shared.tsx` (`ReleaseStatusBadge`, `WilsonInterval`, `CaveatNotice`, `TableScroll`, `ExternalLink`,
`BenchmarkNotFound`). Formatting-only helpers are in `web/src/lib/benchmarkDisplay.ts`. The nav's *Analyze* section
starts with **Benchmarks**; breadcrumbs show the release and model ids from the URL.

Presentation rules: the UI formats served values only (no rate, interval, rank or aggregate is computed in the
browser); every state carries a word or a number, never colour alone; every table has row and column headers and an
accessible name; charts show their values as text; the existing pages' styles are untouched — benchmark CSS uses
benchmark-only class names, with layout overrides of shared classes scoped under `.bench-page`, and
`real-benchmarks.spec.ts` checks that the existing Leaderboard keeps its look.

## 6. Tests

| Test | What it proves |
|---|---|
| `campaigns/tests/test_release_data.py` (pytest) | the committed datasets equal the generator's output (drift fails); the Modern Local v1 facts (ids, 5 × 24 × 5, 600 runs, ranks and passes, digests, task pins, integrity counts, caveat attachment); the historical release is unranked counts only, alphabetical; tampered, resealed, incomplete, out-of-order, rate-inconsistent or contradicted evidence is refused; caveat prose must state its checked numbers; status/kind, ISO date, git ref, invalid JSON, unknown ids and orphan datasets are refused; generation writes nothing but the datasets; every source and evidence link matches the release's git tag; the frozen results still match `SHA256SUMS` |
| `web/tests/benchmarkReleases.spec.ts` (Playwright logic, in `npm run test:focused`) | the datasets validate, and agree with the campaign artifacts read independently; default/ordering semantics of the registry |
| `web/tests/benchmark-releases.spec.ts` (`npm run test:benchmarks`, mocked API, Vite dev server on 4176) | every benchmark surface renders from data (frozen leaderboard rows, caveats, integrity, historical framing, all model pages, methodology); release/model switchers; keyboard matrix; malformed and unknown ids; back/forward; no `NaN`/`undefined` text; axe serious/critical = 0; no page overflow at 375/768/1440; screenshots |
| `web/tests/real-benchmarks.spec.ts` (`npm run test:real`, the built app on a temp copy of the runtime) | the built app serves every benchmark page and the existing Overview, Leaderboard, Jobs, Tasks, Task, Agents and Agent views, with no page errors; the release data stays out of the entry chunk; the existing pages' styles are unchanged |

```bash
PYTHONPATH=campaigns python3 -m afa_campaign release-data --check
python3 -m pytest -p no:cacheprovider campaigns/tests/test_release_data.py
cd web && npm run typecheck && npm run build && npm run test:focused && npm run test:benchmarks
cd web && npm run test:real        # after npm run build: the built app on a temp copy (never reports/)
```
