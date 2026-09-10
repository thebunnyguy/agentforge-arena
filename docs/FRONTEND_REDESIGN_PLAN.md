# AgentForge Arena Frontend Redesign Plan

> **Type:** Phased implementation plan
> **Status:** Draft
> **Source:** Product redesign request; existing `web/`, `afa_api/`, backend tests, and `docs/PRODUCT_APP_DESIGN.md`

## Goal

Transform the existing Vite/React AgentForge Arena frontend from an internal dashboard into a calm, evidence-first local AI evaluation workstation while preserving every existing route, API contract, event flow, and server-owned statistic.

## Scope and non-goals

- **In scope:** frontend presentation, navigation, responsive behavior, accessibility, loading/error states, evaluation setup/monitor/history presentation, and reusable display components.
- **Non-goals:** backend, kernel, runner, task semantics, SQLite data, report math, API response semantics, or new benchmark calculations.
- **Data rule:** every metric, ranking, interval, status, task version, capture state, synthetic baseline, and voided result remains sourced from the existing API. The browser only formats, positions, filters, and links server values.
- **Local-only rule:** no remote fonts, images, analytics, CDNs, or runtime services.

## Retained routes and capabilities

| Route | Redesigned role |
| --- | --- |
| `/` | Evaluation workspace home: readiness, recent evaluations, benchmark snapshot, evidence health |
| `/new` | Five-step Backend → Model → Tasks → Parameters → Review launch workflow |
| `/jobs` | User-facing Evaluations history, with existing job records and actions |
| `/jobs/:jobId` | Live evaluation monitor, cancel/retry, event evidence |
| `/jobs/:jobId/results` | Evaluation results handoff into task/cell/run evidence |
| `/jobs/:jobId/runs/:taskId/:idx` | Job-scoped forensic run detail, resolved by the worker's model identity |
| `/leaderboard` | Kernel-ordered benchmark surface with Wilson interval visualization |
| `/agents` | Agent roster and benchmark summaries |
| `/agent/:agent` | Agent capability profile, domain displayability, task performance links |
| `/tasks` | Searchable task pack and metadata |
| `/task/:taskId` | Task metadata and server-ranked agent comparison |
| `/cell/:agent/:taskId` | Cell conclusion, aggregate evidence, and run table |
| `/cell/:agent/:taskId/run/:idx` | Patch/test/score/provenance forensic evidence |
| `/runs` | Advanced run explorer, reachable but not primary navigation |
| `/reports` | Snapshot provenance, regeneration, and currently supported JSON export |
| `/settings` | Local backend URLs and evaluation defaults |
| `/methodology` | Honest explanation of G, T_hidden, Q, S, X, Wilson ranking, voids, baselines, and displayability |
| `/404` | Recovery-oriented not-found state |

## Navigation and shell

- Replace the crowded dashboard sidebar with `Home`, `Evaluate` (`New evaluation`, `Evaluations`), `Analyze` (`Leaderboard`, `Agents`, `Tasks`), and `Tools` (`Reports`), followed by `Settings` and `Methodology`.
- Keep Runs Explorer as an advanced analysis link, not a primary destination.
- Add a responsive mobile drawer with an accessible menu button, `aria-current`, keyboard focus, and close-on-navigation behavior.
- Use a compact top bar with route context, local API readiness, and a primary New Evaluation action.
- Preserve a provenance footer without making connection protocol terminology the visual focus.

## Visual system

- Warm graphite/near-black surfaces, off-white text hierarchy, quiet borders, citron/electric accent, and restrained green/amber/red/violet semantic colors.
- Sans-serif for interface copy; monospaced text for model IDs, task IDs, run IDs, scores, seeds, code, and patches.
- Use whitespace, typography, rules, and status markers before cards; reserve panels for meaningful evidence groups.
- Add tokens for surfaces, borders, text, accent, semantic states, spacing, radius, type scale, and motion.
- Replace page-specific inline layout styling with named classes where practical.
- Use accessible bracket-and-point Wilson visuals with text equivalents; no frontend statistical computation.
- Add reduced-motion behavior and restrained page/progress transitions.

## Shared presentation components

Create only reusable boundaries supported by multiple routes:

- `AppShell`, responsive `Sidebar`/mobile navigation, `PageHeader`, `SectionHeader`.
- `StatusIndicator`, `Metric`, `MetricGroup`, `EvidenceStrip`, `CaveatBanner`, `EmptyState`, `ErrorState`, `LoadingState`.
- `ConfidenceInterval`, `ProgressBar`, `OutcomeMarker`, `TaskRunGrid`, `EvaluationCard`.
- `BackendOption`, `ModelOption`, `TaskSelector`, `ParameterField`, `ReviewSummary`.
- `EvidencePanel`, `ScoreBreakdown`, `PatchView`, `TestResults`, `AdvancedDetails`.

## Ordered implementation stages

### Stage 1 — Design system and application shell

- Establish tokens, typography, controls, focus states, responsive layout, accessible navigation, and shared state primitives.
- Keep all route URLs and `Layout` composition intact.
- **Check:** typecheck/build; every route still resolves and no external asset is referenced.

### Stage 2 — Home and analysis surfaces

- Redesign Home around readiness, actual persisted evidence, recent evaluations, top server-ordered leaderboard entries, and next action.
- Redesign Leaderboard, Agents, Tasks, Agent Detail, Task Detail, and Domain Matrix around conclusion-first hierarchy while preserving server ordering, Wilson ranges, synthetic baselines, display suppression, and task-version provenance.
- **Check:** API-backed values remain direct renderings; no statistics or mock data enter `web/`.

### Stage 3 — New Evaluation workflow

- Rebuild the five-step wizard with visual backend choices, explicit verification, model IDs from the verification response, searchable/filterable bulk task selection, numeric validation, saved defaults, run-size summary, and a deliberate review/launch state.
- Invalidate verification when backend kind/URL changes; do not let stale responses authorize a changed selection.
- Explain worker/API limitations honestly, including model identity, timeout granularity, and unsupported OpenAI-compatible auth.
- **Check:** mock selection, backend failure, task selection, parameter validation, and launch request preserve existing `JobParams`.

### Stage 4 — Evaluations history and live monitor

- Rename user-facing Jobs to Evaluations while retaining API/job internals.
- Show status/progress/pass/fail/void/reused counters, current task/repeat, grouped task progress, cancellation/retry, coarse live state, and an expandable raw event log.
- Subscribe to every actual worker event type, deduplicate sequence IDs, replay after reconnect, close correctly for queued cancellation and terminal history, and use poll fallback without inflating counters.
- **Check:** existing SSE/poll contract; no invented mid-run stages; historical terminal jobs still expose their event tape.

### Stage 5 — Results and forensic evidence

- Make job results a clear handoff into task/cell/run evidence.
- Rework Cell, Run, Patch, and Test presentation with score primitives, unavailable Q components, capture gaps, synthetic baselines, voided infra failures, task versions, transcript/provenance, and explicit missing evidence.
- Resolve job-scoped run detail using `params.model` to match worker-stamped storage identity; label reused/global evidence where the API cannot provide job-scoped aggregates.
- **Check:** captured, legacy/not-captured, synthetic, failed, and voided states remain distinguishable and deep links remain valid.

### Stage 6 — Supporting pages and report/settings honesty

- Redesign Reports as provenance/export area and expose only currently supported JSON export plus regeneration; do not present unsupported CSV/HTML actions.
- Simplify Settings to existing backend/default controls and verification guidance.
- Make Methodology readable without changing formulas or claims.
- Improve 404, empty, loading, and backend-unavailable recovery states.
- **Check:** report regeneration, JSON download, settings round-trip, and methodology source alignment.

### Stage 7 — Responsive/accessibility/polish and complete verification

- Verify 375px, 768px, 1440px, and 2560px layouts; keep tables and patches usable via controlled scrolling.
- Verify keyboard navigation, headings/labels, `aria-current`, visible focus, semantic table headers, non-color status cues, reduced motion, and text equivalents for visualizations.
- Run frontend typecheck/build and the existing Python suite. Perform browser-level smoke checks if a supported browser harness is available; otherwise record that limit explicitly.
- **Completion:** existing flows remain reachable, every major visual is API-backed, no benchmark math moved into the browser, and the product reads as an intentional local evaluation workstation.

## Known backend/data limitations to preserve in the UI

- Aggregation stores are loaded at API startup; the UI can refresh but must not imply live aggregate recalculation during a running job.
- Worker emits post-`run_once` events; the monitor must not claim live internal patch/test stages.
- `GET /export` currently exposes JSON only; no unsupported export buttons.
- `q_components` are unavailable in persisted v0.1 records.
- Legacy records may lack patch/test artifacts; empty/missing evidence is not success.
- OpenAI-compatible generation currently does not send an authorization header; settings/wizard copy must not imply token support.
- Jobs carry `reused_runs`; reused evidence must not be counted as newly passed runs.
- The app is trusted-local and makes no untrusted-agent isolation claim.

## Final verification and stop conditions

- `cd web && npm install && npm run typecheck && npm run build` succeeds.
- `python3 -m pytest` succeeds without changes to benchmark data or backend math.
- Focused source review confirms no new score/ranking/Wilson/pass@k/domain pooling logic in the frontend.
- Stop if a required UI state is not supported by the API rather than fabricating it; return that limitation for a backend decision instead.
