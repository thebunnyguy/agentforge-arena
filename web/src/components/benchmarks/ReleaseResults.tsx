import { Link } from "react-router-dom";
import { InlineNotice, LinkArrow, Panel, SectionHeader } from "../Primitives";
import { fixed, pct } from "../../lib/format";
import {
  fractionText,
  gigabytesText,
  modelCaveats,
  plainRankingText,
  rankText,
  shortDigest,
  timeoutsText,
} from "../../lib/benchmarkDisplay";
import {
  isCampaignMethodology,
  methodologyPath,
  modelPath,
  type BenchmarkRelease,
  type ReleaseModel,
} from "../../lib/benchmarkReleases";
import { TableScroll, WilsonInterval } from "./shared";
function DetailsLink({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  return (
    <Link className="link-arrow" to={modelPath(release, model.id)}>
      Details<span className="sr-only"> for {model.display_name}</span>
    </Link>
  );
}

function CaveatBadges({
  release,
  model,
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
}) {
  const caveats = modelCaveats(release, model.caveat_ids);
  if (caveats.length === 0) return null;
  return (
    <span className="cell-badges">
      {caveats.map((caveat) => (
        <span
          className="badge warn"
          key={caveat.id}
          data-caveat-badge={caveat.id}
        >
          {caveat.label}
        </span>
      ))}
    </span>
  );
}

/** The row header of a results table: the model's name, tag and caveats. */
function ModelCell({
  release,
  model,
  className = "",
}: {
  release: BenchmarkRelease;
  model: ReleaseModel;
  className?: string;
}) {
  return (
    <th scope="row" className={`primary-cell model-cell row-head ${className}`}>
      <Link to={modelPath(release, model.id)}>{model.display_name}</Link>
      {model.identity.ollama_tag !== model.display_name && (
        <span className="sub-cell mono">{model.identity.ollama_tag}</span>
      )}
      <CaveatBadges release={release} model={model} />
    </th>
  );
}

function IntervalOrDash({ model }: { model: ReleaseModel }) {
  const t = model.totals;
  return t.pass_rate !== undefined &&
    t.wilson_low !== undefined &&
    t.wilson_high !== undefined ? (
    <WilsonInterval
      pHat={t.pass_rate}
      low={t.wilson_low}
      high={t.wilson_high}
    />
  ) : (
    <>—</>
  );
}

/** Small screens: one card per model with every leaderboard column, so
 * nothing needs horizontal scrolling. Shown instead of the table below 781px
 * (the other one is display:none, so only one is in the accessibility tree). */
function LeaderboardCards({
  release,
  labelledBy,
}: {
  release: BenchmarkRelease;
  labelledBy: string;
}) {
  return (
    <ul className="leaderboard-cards" aria-labelledby={labelledBy}>
      {release.models.map((model) => {
        const t = model.totals;
        return (
          <li className="leaderboard-card" key={model.id} data-model={model.id}>
            <div className="card-head">
              <span className="card-rank">
                <span className="card-rank-label">Rank</span>
                <strong className="mono" data-rank="">
                  {rankText(model)}
                </strong>
              </span>
              <div className="card-model">
                <Link to={modelPath(release, model.id)}>
                  {model.display_name}
                </Link>
                {model.identity.ollama_tag !== model.display_name && (
                  <span className="sub-cell mono">
                    {model.identity.ollama_tag}
                  </span>
                )}
                <CaveatBadges release={release} model={model} />
              </div>
            </div>
            <dl className="card-facts">
              <div>
                <dt>Passes</dt>
                <dd className="mono">{fractionText(t.passes, t.runs)}</dd>
              </div>
              <div>
                <dt>Pass rate</dt>
                <dd className="mono">
                  {t.pass_rate !== undefined ? pct(t.pass_rate, 1) : "—"}
                </dd>
              </div>
              <div className="card-wide">
                <dt>Wilson 95%</dt>
                <dd>
                  <IntervalOrDash model={model} />
                </dd>
              </div>
              <div>
                <dt>Coverage</dt>
                <dd className="mono">
                  {fractionText(
                    model.coverage.tasks_with_evidence,
                    model.coverage.tasks_total,
                  )}
                </dd>
              </div>
              <div>
                <dt>Timeouts (full)</dt>
                <dd className="mono">
                  {timeoutsText(t.timeouts, t.request_timeout_hits)}
                </dd>
              </div>
              <div>
                <dt>Agent errors</dt>
                <dd className="mono">{t.agent_errors ?? "—"}</dd>
              </div>
            </dl>
            <DetailsLink release={release} model={model} />
          </li>
        );
      })}
    </ul>
  );
}

/** The official ranked table: rank from the release data, never the index. */
function RankedTable({ release }: { release: BenchmarkRelease }) {
  const methodology = release.methodology;
  const headingId = "release-leaderboard-heading";
  const identitiesId = "release-identities-heading";
  return (
    <Panel>
      <SectionHeader
        id={headingId}
        title="Official leaderboard"
        description={
          isCampaignMethodology(methodology)
            ? plainRankingText(methodology.ranking_method)
            : undefined
        }
        action={
          <LinkArrow to={methodologyPath(release)}>How ranking works</LinkArrow>
        }
      />
      <LeaderboardCards release={release} labelledBy={headingId} />
      <div className="leaderboard-table">
        <TableScroll labelledBy={headingId}>
          <table
            className="data release-leaderboard"
            aria-labelledby={headingId}
          >
            <thead>
              <tr>
                <th scope="col" className="num sticky-rank">
                  rank
                </th>
                <th scope="col" className="sticky-id after-rank">
                  model
                </th>
                <th scope="col" className="num">
                  passes
                </th>
                <th scope="col" className="num">
                  pass rate
                </th>
                <th scope="col">Wilson 95%</th>
                <th scope="col" className="num">
                  coverage
                </th>
                <th scope="col" className="num">
                  timeouts (full)
                </th>
                <th scope="col" className="num">
                  agent errors
                </th>
                <th scope="col">
                  <span className="sr-only">details</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {release.models.map((model) => {
                const t = model.totals;
                return (
                  <tr key={model.id}>
                    <td className="num sticky-rank">
                      <span className="rank-number mono">
                        {rankText(model)}
                      </span>
                    </td>
                    <ModelCell
                      release={release}
                      model={model}
                      className="sticky-id after-rank"
                    />
                    <td className="num mono">
                      {fractionText(t.passes, t.runs)}
                    </td>
                    <td className="num mono">
                      {t.pass_rate !== undefined ? pct(t.pass_rate, 1) : "—"}
                    </td>
                    <td>
                      <IntervalOrDash model={model} />
                    </td>
                    <td className="num mono">
                      {fractionText(
                        model.coverage.tasks_with_evidence,
                        model.coverage.tasks_total,
                      )}
                    </td>
                    <td className="num mono">
                      {timeoutsText(t.timeouts, t.request_timeout_hits)}
                    </td>
                    <td className="num mono">{t.agent_errors ?? "—"}</td>
                    <td>
                      <DetailsLink release={release} model={model} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableScroll>
      </div>
      <InlineNotice tone="info">
        <span>
          Each pass rate sits beside its Wilson 95% interval: the interval is
          the plausible range around the observed rate, not a progress bar, and
          overlapping intervals mean limited separation. Timeouts count runs
          classified as timeouts; the number in parentheses is how many of them
          were full model-request timeouts.
        </span>
      </InlineNotice>
      <details className="supporting-details">
        <summary id={identitiesId}>Model identities</summary>
        <TableScroll labelledBy={identitiesId}>
          <table className="data" aria-labelledby={identitiesId}>
            <thead>
              <tr>
                <th scope="col" className="sticky-id">
                  model
                </th>
                <th scope="col">Ollama tag</th>
                <th scope="col">family</th>
                <th scope="col" className="num">
                  parameters
                </th>
                <th scope="col">quantization</th>
                <th scope="col">format</th>
                <th scope="col" className="num">
                  download size
                </th>
                <th scope="col">digest</th>
              </tr>
            </thead>
            <tbody>
              {release.models.map((model) => (
                <tr key={model.id}>
                  <th scope="row" className="primary-cell row-head sticky-id">
                    {model.display_name}
                  </th>
                  <td className="mono">{model.identity.ollama_tag}</td>
                  <td className="mono">{model.identity.family ?? "—"}</td>
                  <td className="num mono">
                    {model.identity.parameter_size ?? "—"}
                  </td>
                  <td className="mono">{model.identity.quantization ?? "—"}</td>
                  <td className="mono">{model.identity.format ?? "—"}</td>
                  <td className="num mono">
                    {gigabytesText(model.identity.download_bytes)}
                  </td>
                  <td className="mono" title={model.identity.digest ?? ""}>
                    {model.identity.digest
                      ? shortDigest(model.identity.digest)
                      : "not recorded"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </details>
    </Panel>
  );
}

/** A historical record: counts as recorded, listed alphabetically by Ollama
 * tag (the dataset's order). The order is not a ranking. */
function RecordedTable({ release }: { release: BenchmarkRelease }) {
  const methodology = release.methodology;
  const formula = isCampaignMethodology(methodology)
    ? null
    : methodology.scoring_formula.join(", ");
  const headingId = "release-recorded-heading";
  return (
    <Panel>
      <SectionHeader
        id={headingId}
        title="Recorded results (unranked)"
        description="Pass counts, timeouts and mean final scores as recorded, listed alphabetically by Ollama tag. The order is not a ranking."
      />
      <TableScroll labelledBy={headingId}>
        <table className="data release-recorded" aria-labelledby={headingId}>
          <thead>
            <tr>
              <th scope="col" className="sticky-id">
                model
              </th>
              <th scope="col" className="num">
                passes / runs
              </th>
              <th scope="col" className="num">
                timeouts
              </th>
              <th scope="col" className="num">
                mean final score{formula ? ` (formula ${formula})` : ""}
              </th>
              <th scope="col">
                <span className="sr-only">details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {release.models.map((model) => (
              <tr key={model.id}>
                <ModelCell
                  release={release}
                  model={model}
                  className="sticky-id"
                />
                <td className="num mono">
                  {fractionText(model.totals.passes, model.totals.runs)}
                </td>
                <td className="num mono">
                  {timeoutsText(model.totals.timeouts)}
                </td>
                <td className="num mono">
                  {fixed(model.totals.mean_final_score, 3)}
                </td>
                <td>
                  <DetailsLink release={release} model={model} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <p className="note muted">
        This release is unranked: no positions or confidence intervals are
        derived from these counts, and they are never pooled with another
        release.
      </p>
    </Panel>
  );
}

export function ReleaseResults({ release }: { release: BenchmarkRelease }) {
  return release.ranked ? (
    <RankedTable release={release} />
  ) : (
    <RecordedTable release={release} />
  );
}
