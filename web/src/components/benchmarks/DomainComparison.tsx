import { useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Panel, SectionHeader } from "../Primitives";
import { fixed, pct } from "../../lib/format";
import { intervalText } from "../../lib/benchmarkDisplay";
import {
  modelPath,
  type BenchmarkRelease,
  type ReleaseDomainResult,
} from "../../lib/benchmarkReleases";
import { TableScroll, WilsonInterval } from "./shared";

/** One model's served domain results as rows: exact pooled rate, one
 * point-and-interval plot with the interval as text, and the evidence behind
 * it. Shared with the model page. */
export function DomainProfile({
  domains,
}: {
  domains: readonly ReleaseDomainResult[];
}) {
  return (
    <div className="domain-list bench-domain-list">
      {domains.map((domain) => (
        <div className="domain-row" key={domain.domain}>
          <div className="domain-name">
            <span>{domain.domain}</span>
            <small>
              n_eff {fixed(domain.n_eff, 1)} · {domain.n_tasks} tasks ·{" "}
              {domain.n_runs} runs
            </small>
          </div>
          {domain.displayable ? (
            <>
              <span className="domain-value mono">
                {pct(domain.pooled_pass_rate, 1)}
              </span>
              <WilsonInterval
                pHat={domain.pooled_pass_rate}
                low={domain.wilson_low}
                high={domain.wilson_high}
                width={260}
              />
            </>
          ) : (
            <span className="badge warn">not displayable</span>
          )}
        </div>
      ))}
    </div>
  );
}

export function DomainComparison({ release }: { release: BenchmarkRelease }) {
  const [modelId, setModelId] = useState(release.models[0]?.id ?? "");
  if (release.domains.length === 0) return null;
  const selected =
    release.models.find((model) => model.id === modelId) ?? release.models[0];
  const byDomain = (domains: readonly ReleaseDomainResult[], name: string) =>
    domains.find((domain) => domain.domain === name);
  // Tasks and runs per domain are the same for every model; read them from
  // the first model that serves the domain.
  const domainSize = (name: string) =>
    release.models
      .map((model) => byDomain(model.domains, name))
      .find((domain) => domain !== undefined);
  const headingId = "release-domains-heading";

  return (
    <Panel>
      <SectionHeader
        id={headingId}
        title="Domain comparison"
        description="Weighted pooled pass rate per domain, as computed by the kernel for each model. Each cell shows the pooled rate with its Wilson 95% interval below, and each column header the domain's tasks and runs; overlapping intervals mean limited separation. A domain is displayable with at least 5 tasks and 25 runs; shading follows the rate only."
      />
      <TableScroll labelledBy={headingId}>
        <table
          className="data matrix domain-matrix"
          aria-labelledby={headingId}
        >
          <thead>
            <tr>
              <th scope="col" className="sticky-id">
                model
              </th>
              {release.domains.map((domain) => {
                const size = domainSize(domain);
                return (
                  <th scope="col" key={domain}>
                    {domain}
                    {size && (
                      <small className="domain-size">
                        {size.n_tasks} tasks · {size.n_runs} runs
                      </small>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {release.models.map((model) => (
              <tr key={model.id}>
                <th scope="row" className="primary-cell row-head sticky-id">
                  <Link to={modelPath(release, model.id)}>
                    {model.display_name}
                  </Link>
                </th>
                {release.domains.map((name) => {
                  const cell = byDomain(model.domains, name);
                  if (!cell)
                    return (
                      <td key={name} className="cell">
                        no data
                      </td>
                    );
                  if (!cell.displayable)
                    return (
                      <td key={name} className="cell">
                        suppressed
                      </td>
                    );
                  return (
                    <td
                      key={name}
                      className="cell matrix-heat"
                      style={
                        { "--heat": cell.pooled_pass_rate } as CSSProperties
                      }
                    >
                      <span className="cell-rate mono">
                        {pct(cell.pooled_pass_rate, 1)}
                      </span>
                      <small className="cell-ci mono">
                        <span className="sr-only">Wilson 95% interval </span>
                        {intervalText(cell.wilson_low, cell.wilson_high)}
                      </small>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>

      <div className="toolbar domain-toolbar">
        <label htmlFor="domain-model">Domain profile for</label>
        <select
          id="domain-model"
          value={selected.id}
          onChange={(event) => setModelId(event.target.value)}
        >
          {release.models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.display_name} ({model.id})
            </option>
          ))}
        </select>
      </div>
      <DomainProfile domains={selected.domains} />
    </Panel>
  );
}
