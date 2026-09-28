import { BookOpen, History } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  InlineNotice,
  LinkArrow,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { DomainComparison } from "../components/benchmarks/DomainComparison";
import { EvidencePanel } from "../components/benchmarks/EvidencePanel";
import { IntegrityPanel } from "../components/benchmarks/IntegrityPanel";
import { ReadingResults } from "../components/benchmarks/ReadingResults";
import { ReleaseHeadline } from "../components/benchmarks/ReleaseHeadline";
import { ReleaseResults } from "../components/benchmarks/ReleaseResults";
import { ReleaseSelector } from "../components/benchmarks/ReleaseSelector";
import { TaskMatrix } from "../components/benchmarks/TaskMatrix";
import {
  BenchmarkNotFound,
  CaveatNotice,
} from "../components/benchmarks/shared";
import { benchmarkReleases, defaultRelease } from "../data/benchmark-releases";
import {
  caveatsFor,
  findRelease,
  methodologyPath,
  type BenchmarkRelease as Release,
} from "../lib/benchmarkReleases";

/** Release-level caveats. A release's comparability statement leads, as a
 * warning, with the points of the caveat that carries the same statement. */
function ReleaseCaveats({ release }: { release: Release }) {
  const caveats = caveatsFor(release, null);
  const comparability = release.comparability;
  const matching = comparability
    ? caveats.find((caveat) => caveat.summary === comparability)
    : undefined;
  const rest = caveats.filter((caveat) => caveat !== matching);
  return (
    <>
      {comparability &&
        (matching ? (
          <CaveatNotice caveat={matching} tone="warn" />
        ) : (
          <InlineNotice tone="warn">
            <History size={16} aria-hidden="true" />
            <span>{comparability}</span>
          </InlineNotice>
        ))}
      {rest.map((caveat) => (
        <CaveatNotice caveat={caveat} key={caveat.id} />
      ))}
    </>
  );
}

/** For a record the live Explorer pages also draw from: say what they show. */
function LiveExplorerNote({ release }: { release: Release }) {
  if (release.status !== "HISTORICAL") return null;
  return (
    <InlineNotice tone="info">
      <History size={16} aria-hidden="true" />
      <span>
        The live <Link to="/leaderboard">Leaderboard</Link> and{" "}
        <Link to="/tasks">Tasks</Link> pages are not this release. They show the
        app's working database, which is seeded from this record by default, and
        they use the current task versions, so their figures differ from the
        recorded counts here.
      </span>
    </InlineNotice>
  );
}

function ReleaseView({ release }: { release: Release }) {
  return (
    <div className="bench-page">
      <PageHeader
        eyebrow="Benchmark release"
        title={release.title}
        description={release.summary}
        actions={
          <Link className="btn btn-secondary" to={methodologyPath(release)}>
            <BookOpen size={15} aria-hidden="true" /> Methodology &amp;
            provenance
          </Link>
        }
      />
      {release.comparability && <ReleaseCaveats release={release} />}
      <ReleaseSelector
        release={release}
        releases={benchmarkReleases}
        defaultId={defaultRelease.id}
      />
      <ReleaseHeadline release={release} />
      {!release.comparability && <ReleaseCaveats release={release} />}
      <ReleaseResults release={release} />
      <LiveExplorerNote release={release} />
      <ReadingResults release={release} />
      <DomainComparison release={release} />
      <TaskMatrix release={release} />
      <IntegrityPanel release={release} />
      <EvidencePanel release={release} />
      <Panel>
        <SectionHeader
          title="Methodology & provenance"
          description={
            release.ranked
              ? "Generation settings, evaluation identity, model and task pins, and the hashes this release is checked against."
              : "Documented generation settings per group, the scoring formula, recorded versus current task versions, and what was not recorded."
          }
          action={
            <LinkArrow to={methodologyPath(release)}>
              Open methodology
            </LinkArrow>
          }
        />
      </Panel>
    </div>
  );
}

export function BenchmarkRelease() {
  const { releaseId } = useParams();
  const release =
    releaseId === undefined
      ? defaultRelease
      : findRelease(benchmarkReleases, releaseId);
  if (!release)
    return (
      <BenchmarkNotFound
        title="Release not found"
        message={
          <>
            No benchmark release has the id{" "}
            <span className="mono">{releaseId}</span>.
          </>
        }
        backTo="/benchmarks"
        backLabel="Open the current benchmark release"
      />
    );
  // Keyed so per-release view state (selected cell, domain model) resets.
  return <ReleaseView key={release.id} release={release} />;
}
