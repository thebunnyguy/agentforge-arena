import type { ReactNode } from "react";
import { Layers } from "lucide-react";
import type { EvidenceScope } from "../api/types";
import { EVIDENCE_SCOPE_OPTIONS, coverageText } from "../lib/format";

// Small labelled evidence selector (real <label>), bound by the caller to the
// URL query ?evidence=.
export function EvidenceScopeSelect({
  scope,
  onChange,
  id = "evidence-scope",
}: {
  scope: EvidenceScope;
  onChange: (next: EvidenceScope) => void;
  id?: string;
}) {
  return (
    <div className="scope-select">
      <label htmlFor={id}>Evidence scope</label>
      <select
        id={id}
        value={scope}
        onChange={(event) => onChange(event.target.value as EvidenceScope)}
      >
        {EVIDENCE_SCOPE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function scopeCopy(scope: EvidenceScope): {
  title: string;
  body: string;
  tone: "current" | "synthetic";
} {
  switch (scope) {
    case "synthetic":
      return {
        title: "Synthetic - not benchmark evidence.",
        body: "Development view of mock runs only. These rows are excluded from every benchmark ranking and must not be read as model results.",
        tone: "synthetic",
      };
    case "all":
      return {
        title: "All evidence classes, including synthetic mock runs.",
        body: "Not a benchmark view: mock (synthetic) rows are mixed in with real and legacy rows. Only the current task version of each task is aggregated.",
        tone: "synthetic",
      };
    case "real":
      return {
        title: "CURRENT benchmark evidence - real-provider runs only.",
        body: "Legacy rows (provider unknown) and mock rows are excluded. Only runs at each task's current version are aggregated; older versions stay available as history.",
        tone: "current",
      };
    default:
      return {
        title: "CURRENT benchmark evidence.",
        body: "Only runs at each task's current version are aggregated; older versions are kept as historical evidence and are never pooled. Mock (synthetic) runs are excluded.",
        tone: "current",
      };
  }
}

// Labels an aggregate page as CURRENT benchmark evidence, shows the server
// coverage ("n/24 tasks with current evidence") and hosts the evidence selector.
export function EvidenceScopeBanner({
  scope,
  onScopeChange,
  coverage,
  children,
}: {
  scope: EvidenceScope;
  onScopeChange: (next: EvidenceScope) => void;
  /** Server numbers, e.g. overview.current_benchmark. */
  coverage?: { withCurrent: number; total: number } | null;
  children?: ReactNode;
}) {
  const copy = scopeCopy(scope);
  const partial = coverage ? coverage.withCurrent < coverage.total : false;
  return (
    <section
      className={`scope-banner scope-${copy.tone}`}
      aria-label="Benchmark evidence notice"
    >
      <Layers size={17} aria-hidden="true" />
      <div className="scope-banner-body">
        <p>
          <strong>{copy.title}</strong> {copy.body}
        </p>
        {coverage && (
          <p className="scope-coverage">
            <span className="mono">
              Coverage: {coverageText(coverage.withCurrent, coverage.total)}
            </span>
            {partial &&
              ` - partial coverage. Ranks compare models only on the tasks that have current evidence; they are not a full ${coverage.total}-task benchmark ranking.`}
          </p>
        )}
        {children}
      </div>
      <EvidenceScopeSelect scope={scope} onChange={onScopeChange} />
    </section>
  );
}
