import type { ReactNode } from "react";
import { Panel, SectionHeader } from "../Primitives";
import { fractionText } from "../../lib/benchmarkDisplay";
import {
  isCampaignMethodology,
  type BenchmarkRelease,
  type ReleaseIntegrity,
} from "../../lib/benchmarkReleases";

type State = { word: string; tone: "good" | "warn" | "bad" | "neutral" };

const NONE: State = { word: "none", tone: "good" };
const FOUND: State = { word: "present", tone: "bad" };

/** Word for counts that should all be zero. */
const zero = (...values: number[]): State =>
  values.every((value) => value === 0) ? NONE : FOUND;
/** Word for an "x of y" fact that should be complete. */
const whole = (value: number, of: number, word = "complete"): State =>
  value === of ? { word, tone: "good" } : { word: "incomplete", tone: "warn" };

interface Fact {
  label: string;
  value: ReactNode;
  state: State;
  detail?: string;
}

function facts(integrity: ReleaseIntegrity): Fact[] {
  const classes = integrity.evidence_classes;
  const clean = integrity.complete && integrity.problems.length === 0;
  const runtime = integrity.runtime;
  return [
    {
      label: "Accepted runs",
      value: `${fractionText(integrity.accepted_runs, integrity.planned_runs)} planned`,
      state: whole(integrity.accepted_runs, integrity.planned_runs),
    },
    {
      label: "Accepted evaluations",
      value: `${fractionText(integrity.accepted_evaluations, integrity.planned_evaluations)} planned`,
      state: whole(
        integrity.accepted_evaluations,
        integrity.planned_evaluations,
      ),
    },
    {
      label: "Models complete",
      value: fractionText(integrity.models_complete, integrity.models_total),
      state: whole(integrity.models_complete, integrity.models_total),
    },
    {
      label: "Task coverage",
      value: `${fractionText(integrity.task_coverage_min, integrity.tasks_total)} tasks for every model`,
      state: whole(integrity.task_coverage_min, integrity.tasks_total),
    },
    {
      label: "Task versions & digests pinned",
      value: `${integrity.task_pins.tasks} tasks`,
      state: clean
        ? { word: "verified", tone: "good" }
        : { word: "see problems", tone: "warn" },
      detail: integrity.task_pins.basis,
    },
    {
      label: "Real backend evidence",
      value: `${classes.real} runs · backend ${integrity.backend_kind}`,
      state: whole(classes.real, integrity.accepted_runs, "real"),
    },
    {
      label: "Synthetic (mock) evidence",
      value: `${classes.synthetic} runs`,
      state: zero(classes.synthetic),
    },
    {
      label: "Legacy evidence",
      value: `${classes.legacy} runs`,
      state: zero(classes.legacy),
    },
    {
      label: "Provenance conflicts",
      value: `${classes.conflict} runs`,
      state: zero(classes.conflict),
    },
    {
      label: "Missing runs",
      value: `${integrity.missing_runs} runs · ${integrity.missing_evaluations} evaluations`,
      state: zero(integrity.missing_runs, integrity.missing_evaluations),
    },
    {
      label: "Extra campaign runs",
      value: `${integrity.extra_runs} runs`,
      state: zero(integrity.extra_runs),
    },
    {
      label: "Untracked / disowned / superseded / voided",
      value: [
        integrity.untracked_evaluations,
        integrity.disowned_evaluations,
        integrity.superseded_entries,
        integrity.voided_runs,
      ].join(" / "),
      state: zero(
        integrity.untracked_evaluations,
        integrity.disowned_evaluations,
        integrity.superseded_entries,
        integrity.voided_runs,
      ),
    },
    {
      label: "Model identity",
      value: `${fractionText(integrity.model_identity.cells_at_pinned_digest, integrity.model_identity.cells_total)} cells at the pinned digest · Ollama ${integrity.model_identity.ollama_version}`,
      state: whole(
        integrity.model_identity.cells_at_pinned_digest,
        integrity.model_identity.cells_total,
        "verified",
      ),
    },
    {
      label: "Runtime release",
      value: `${runtime.tag} · ${fractionText(runtime.launches_with_code_check, runtime.launches)} launches code-checked`,
      state: whole(
        runtime.launches_with_code_check,
        runtime.launches,
        "verified",
      ),
    },
    {
      label: "Historical evidence unchanged",
      value: integrity.historical_evidence_unchanged ? "yes" : "no",
      state: integrity.historical_evidence_unchanged
        ? { word: "verified", tone: "good" }
        : { word: "changed", tone: "bad" },
    },
    {
      label: "Validator problems / warnings",
      value: `${integrity.problems.length} / ${integrity.warnings.length}`,
      state: zero(integrity.problems.length, integrity.warnings.length),
    },
  ];
}

export function IntegrityPanel({ release }: { release: BenchmarkRelease }) {
  const integrity = release.integrity;
  const methodology = release.methodology;
  return (
    <Panel>
      <SectionHeader
        title="Benchmark integrity"
        description={
          integrity
            ? "What the campaign validator and the completeness receipt establish for this release. Each fact carries its own state."
            : "This record predates the evaluation-integrity system, so no completeness receipt or provenance checks exist for it."
        }
      />
      {integrity ? (
        <>
          <dl className="integrity-list">
            {facts(integrity).map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd className="integrity-value mono">
                  {fact.value}
                  {fact.detail && (
                    <span className="integrity-detail">{fact.detail}</span>
                  )}
                </dd>
                <dd className="integrity-state">
                  <span className={`badge ${fact.state.tone}`}>
                    {fact.state.word}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
          <h3>Not claimed</h3>
          <ul className="not-claimed">
            {integrity.not_claimed.map((item) => (
              <li key={item.property}>
                <div className="reading-head">
                  <strong>{item.property}</strong>
                  <span className="badge warn">{item.status}</span>
                </div>
                <p>{item.note}</p>
                <p className="notice-source">
                  Source: <span className="mono">{item.source}</span>
                </p>
              </li>
            ))}
          </ul>
        </>
      ) : (
        !isCampaignMethodology(methodology) && (
          <>
            <h3>Not recorded</h3>
            <ul className="not-recorded">
              {methodology.not_recorded.map((item) => (
                <li key={item}>
                  <span className="badge neutral">not recorded</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </>
        )
      )}
    </Panel>
  );
}
