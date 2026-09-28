import { LinkArrow, Panel, SectionHeader } from "../Primitives";
import {
  findModel,
  modelPath,
  type BenchmarkRelease,
} from "../../lib/benchmarkReleases";

/** Model-specific caveats in a calm list next to the results they qualify:
 * each caveat's summary and every one of its points, as the dataset carries
 * them. Renders nothing when the release has no model caveats. */
export function ReadingResults({ release }: { release: BenchmarkRelease }) {
  const caveats = release.caveats.filter((caveat) => caveat.model !== null);
  if (caveats.length === 0) return null;
  return (
    <Panel className="reading-results">
      <SectionHeader
        title="Reading these results"
        description="Required context for individual models, from the release's caveats. Each model's page repeats it next to that model's numbers."
      />
      <ul className="reading-list">
        {caveats.map((caveat) => {
          const model = findModel(release, caveat.model ?? undefined);
          return (
            <li key={caveat.id} data-caveat={caveat.id}>
              <div className="reading-head">
                <span className="badge neutral">{caveat.label}</span>
                <strong>{model?.display_name ?? caveat.model}</strong>
                {model && (
                  <span className="mono reading-tag">
                    {model.identity.ollama_tag}
                  </span>
                )}
              </div>
              <p>{caveat.summary}</p>
              {caveat.points.length > 0 && (
                <ul className="reading-points">
                  {caveat.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              )}
              <p className="notice-source">
                Source: <span className="mono">{caveat.source}</span>
              </p>
              {model && (
                <LinkArrow to={modelPath(release, model.id)}>
                  {model.display_name} details
                </LinkArrow>
              )}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
