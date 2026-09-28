import { Link } from "react-router-dom";
import { Panel } from "../Primitives";
import {
  formatReleaseDate,
  releaseDateLabel,
  repositoryCommitUrl,
  repositoryRefLabel,
  repositoryTreeUrl,
  shortCommit,
} from "../../lib/benchmarkDisplay";
import {
  releasePath,
  STATUS_DESCRIPTIONS,
  type BenchmarkRelease,
} from "../../lib/benchmarkReleases";
import { ExternalLink, ReleaseStatusBadge } from "./shared";

/** Release switcher as plain links (navigation happens only on an explicit
 * activation, never on a form-control change), plus the release's status,
 * date and frozen ref. */
export function ReleaseSelector({
  release,
  releases,
  defaultId,
}: {
  release: BenchmarkRelease;
  releases: readonly BenchmarkRelease[];
  defaultId: string;
}) {
  const { ref, commit } = release.repository;
  return (
    <Panel className="release-bar">
      <nav className="release-switch" aria-labelledby="release-switch-label">
        <span className="fact-label" id="release-switch-label">
          Benchmark releases
        </span>
        <ul className="chip-list">
          {releases.map((option) => {
            const current = option.id === release.id;
            return (
              <li key={option.id}>
                <Link
                  className="version-chip release-chip"
                  to={releasePath(option)}
                  aria-current={current ? "page" : undefined}
                  data-release={option.id}
                >
                  <span>{option.short_title}</span>
                  <span className="chip-sep" aria-hidden="true">
                    ·
                  </span>
                  <span className="chip-status">{option.status}</span>
                  {option.id === defaultId && (
                    <>
                      <span className="chip-sep" aria-hidden="true">
                        ·
                      </span>
                      <span>default</span>
                    </>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <dl className="kv release-facts">
        <dt>Status</dt>
        <dd className="release-status">
          <span className="badge-inline">
            <ReleaseStatusBadge status={release.status} />
            {release.id === defaultId && (
              <span className="badge neutral">current default</span>
            )}
          </span>
          <span className="release-status-text">
            {STATUS_DESCRIPTIONS[release.status]}
          </span>
        </dd>
        <dt>{releaseDateLabel(release.status)}</dt>
        <dd>{formatReleaseDate(release.released_at)}</dd>
        <dt>{repositoryRefLabel(release.status)}</dt>
        <dd>
          {ref ? (
            <ExternalLink href={repositoryTreeUrl(release)}>{ref}</ExternalLink>
          ) : (
            "not recorded"
          )}
          {commit && (
            <>
              {" "}
              at commit{" "}
              <ExternalLink href={repositoryCommitUrl(release)}>
                {shortCommit(commit)}
              </ExternalLink>
            </>
          )}
        </dd>
      </dl>
    </Panel>
  );
}
