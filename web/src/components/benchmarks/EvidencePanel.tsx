import { Panel, SectionHeader } from "../Primitives";
import { datasetPath, RELEASE_DATA_COMMAND } from "../../lib/benchmarkDisplay";
import {
  evidenceUrl,
  type BenchmarkRelease,
  type EvidenceLink,
} from "../../lib/benchmarkReleases";
import { ExternalLink } from "./shared";

function LinkList({
  release,
  links,
}: {
  release: BenchmarkRelease;
  links: readonly EvidenceLink[];
}) {
  const ref = release.repository.ref;
  return (
    <ul className="evidence-links">
      {links.map((link) => (
        <li key={link.path}>
          <div className="evidence-link-text">
            <strong>{link.label}</strong>
            <span className="mono evidence-path">{link.path}</span>
          </div>
          <ExternalLink href={evidenceUrl(release, link.path)}>
            {ref ? `View at ${ref}` : "View"}
            <span className="sr-only">: {link.label}</span>
          </ExternalLink>
        </li>
      ))}
    </ul>
  );
}

/** The release dataset, the command that regenerates it, and the hashed
 * source files it was generated from. */
export function DatasetSources({ release }: { release: BenchmarkRelease }) {
  return (
    <>
      <h3>This page's dataset</h3>
      <dl className="kv">
        <dt>dataset</dt>
        <dd>{datasetPath(release)}</dd>
        <dt>regenerate with</dt>
        <dd>
          <code>{RELEASE_DATA_COMMAND}</code>
        </dd>
      </dl>
      <details className="supporting-details">
        <summary>Dataset sources ({release.sources.length} files)</summary>
        <ul className="source-list">
          {release.sources.map((source) => (
            <li key={source.path}>
              <span className="mono">{source.path}</span>
              <span className="mono source-hash">sha256 {source.sha256}</span>
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}

/** The committed files a release is built from, the dataset itself, and the
 * command that regenerates it. */
export function EvidencePanel({ release }: { release: BenchmarkRelease }) {
  const releaseLinks = release.evidence_links.filter((link) => !link.model);
  const modelLinks = release.evidence_links.filter((link) => link.model);
  return (
    <Panel>
      <SectionHeader
        title="Evidence"
        description={
          release.status === "HISTORICAL"
            ? "Committed files behind this record, linked at the git ref that carries them (the record predates that ref)."
            : "Committed files behind this release, linked at its frozen git ref."
        }
      />
      <LinkList release={release} links={releaseLinks} />
      {modelLinks.length > 0 && (
        <>
          <h3>Model receipts</h3>
          <LinkList release={release} links={modelLinks} />
        </>
      )}
      <DatasetSources release={release} />
    </Panel>
  );
}
