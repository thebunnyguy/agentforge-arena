import { Cpu, MapPin } from "lucide-react";
import { Link } from "react-router-dom";
import { InlineNotice } from "../Primitives";
import { formatRunWindow } from "../../lib/benchmarkDisplay";
import {
  isCampaignMethodology,
  methodologyPath,
  type BenchmarkRelease,
} from "../../lib/benchmarkReleases";

/** Visible marker for a fact taken from the campaign documentation rather
 * than the result artifacts; links to the methodology page, which shows the
 * source of each one. */
function DocumentedMarker({
  release,
  fact,
}: {
  release: BenchmarkRelease;
  fact: string;
}) {
  return (
    <Link className="doc-marker" to={methodologyPath(release)}>
      documented
      <span className="sr-only">
        : source of the {fact} on the methodology page
      </span>
    </Link>
  );
}

/** The release at a glance, built only from its counts, headline and
 * environment. A release without an environment (historical) gets its counts
 * and run window, and no hardware or cost claim. */
export function ReleaseHeadline({ release }: { release: BenchmarkRelease }) {
  const { counts, headline, environment, methodology } = release;
  const campaign = isCampaignMethodology(methodology) ? methodology : null;
  const recorded = isCampaignMethodology(methodology) ? null : methodology;
  const facts: Array<{ value: number; label: string }> = [
    {
      value: counts.runs,
      label: campaign?.mode === "fresh" ? "fresh runs" : "recorded runs",
    },
  ];
  if (counts.evaluations !== null)
    facts.push({
      value: counts.evaluations,
      label: "evaluations (model × task cells)",
    });
  facts.push(
    { value: counts.models, label: "models" },
    { value: counts.tasks, label: campaign ? "audited tasks" : "tasks" },
    { value: counts.repetitions, label: "repetitions per model/task" },
  );

  return (
    <div className="release-headline">
      <ul className="headline-strip" aria-label="Release at a glance">
        {facts.map((fact) => (
          <li key={fact.label}>
            <strong className="mono">{fact.value}</strong>{" "}
            <span>{fact.label}</span>
          </li>
        ))}
      </ul>
      {headline && environment ? (
        <>
          <ul className="headline-context" aria-label="Environment">
            <li>{headline.inference}</li>
            <li>
              <Cpu size={13} aria-hidden="true" />
              {environment.hardware.chip} · {environment.hardware.memory}
              <DocumentedMarker release={release} fact="hardware" />
            </li>
            <li>
              {headline.paid_api_cost.text}
              <DocumentedMarker release={release} fact="paid API cost" />
            </li>
          </ul>
          <InlineNotice tone="info">
            <MapPin size={16} aria-hidden="true" />
            <span>{environment.scope}</span>
          </InlineNotice>
        </>
      ) : (
        recorded && (
          <p className="note muted headline-window">
            Run window (as recorded):{" "}
            <span className="mono">{formatRunWindow(recorded.run_window)}</span>
          </p>
        )
      )}
    </div>
  );
}
