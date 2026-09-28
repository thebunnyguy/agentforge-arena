// Display helpers for the Benchmark Releases pages. Formatting only: each
// function turns a value the release dataset already carries into text. None
// of them derives a rate, interval, rank or aggregate.
//
// Side-effect free (types plus the pure format.ts helpers) so the logic tests
// can load it.

import { pct, rankLabel } from "./format";
import type {
  BenchmarkRelease,
  ReleaseCaveat,
  ReleaseModel,
  ReleaseStatus,
  ReleaseTaskResult,
} from "./benchmarkReleases";

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** "2026-09-28" -> "Sep 28, 2026". Parsed by hand so a date-only value never
 * shifts a day in a negative-UTC time zone (format.ts formatDate drops the
 * year and is meant for timestamps). Anything else is returned unchanged. */
export function formatReleaseDate(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const month = MONTHS[Number(match[2]) - 1];
  if (!month) return value;
  return `${month} ${Number(match[3])}, ${match[1]}`;
}

/** A recorded timestamp ("2026-09-27T23:09:55Z" or the historical database's
 * "2026-06-18 06:11:14", both UTC) -> "2026-09-27 23:09 UTC", year included
 * and independent of the viewer's time zone. */
export function formatUtcTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(value);
  return match ? `${match[1]} ${match[2]} UTC` : value;
}

export function formatRunWindow(
  window: { started_at: string; finished_at: string } | null | undefined,
): string {
  if (!window) return "—";
  return `${formatUtcTimestamp(window.started_at)} → ${formatUtcTimestamp(window.finished_at)}`;
}

/** Wilson 95% interval as text: "72.0–86.2%". */
export function intervalText(low: number, high: number, digits = 1): string {
  return `${(low * 100).toFixed(digits)}–${(high * 100).toFixed(digits)}%`;
}

/** "96 / 120" */
export function fractionText(value: number, of: number): string {
  return `${value} / ${of}`;
}

/** "105 (83 full)"; without a full-request count only the timeouts. */
export function timeoutsText(
  timeouts: number | undefined,
  fullRequest?: number,
): string {
  if (timeouts === undefined) return "not recorded";
  return fullRequest === undefined
    ? String(timeouts)
    : `${timeouts} (${fullRequest} full)`;
}

/** Registry download size in decimal gigabytes: 18556700222 -> "18.56 GB". */
export function gigabytesText(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "not recorded";
  return `${(bytes / 1e9).toFixed(2)} GB`;
}

/** [42, 43, 44, 45, 46] -> "42–46"; a non-consecutive list is listed. */
export function seedsText(seeds: readonly number[]): string {
  if (seeds.length === 0) return "—";
  const consecutive = seeds.every(
    (seed, index) => index === 0 || seed === seeds[index - 1] + 1,
  );
  return consecutive && seeds.length > 2
    ? `${seeds[0]}–${seeds[seeds.length - 1]}`
    : seeds.join(", ");
}

/** First characters of a hex digest, without a "sha256:" prefix. */
export function shortDigest(digest: string | null | undefined, length = 12) {
  if (!digest) return "—";
  return digest.replace(/^sha256:/, "").slice(0, length);
}

export function shortCommit(commit: string | null | undefined): string {
  return commit ? commit.slice(0, 7) : "—";
}

export function repositoryTreeUrl(release: BenchmarkRelease): string | null {
  const { url, ref } = release.repository;
  return url && ref ? `${url}/tree/${encodeURIComponent(ref)}` : null;
}

export function repositoryCommitUrl(release: BenchmarkRelease): string | null {
  const { url, commit } = release.repository;
  return url && commit ? `${url}/commit/${encodeURIComponent(commit)}` : null;
}

/** Where the release's dataset lives in the repository. */
export function datasetPath(release: BenchmarkRelease): string {
  return `web/src/data/benchmark-releases/${release.id}.json`;
}

/** The command that regenerates every release dataset from committed evidence. */
export const RELEASE_DATA_COMMAND =
  "PYTHONPATH=campaigns python3 -m afa_campaign release-data";

/** Badge tone for a release status; the status word is always shown with it. */
export function statusTone(
  status: ReleaseStatus,
): "good" | "warn" | "neutral" | "void" {
  switch (status) {
    case "OFFICIAL":
      return "good";
    case "EXPERIMENTAL":
      return "void";
    case "HISTORICAL":
      return "warn";
    default:
      return "neutral";
  }
}

/** A model's caveats, resolved from its caveat_ids (dataset order). */
export function modelCaveats(
  release: BenchmarkRelease,
  caveatIds: readonly string[],
): ReleaseCaveat[] {
  return caveatIds
    .map((id) => release.caveats.find((caveat) => caveat.id === id))
    .filter((caveat): caveat is ReleaseCaveat => caveat !== undefined);
}

/** A model's rank exactly as served: rank.low (or "low–high" for a tie band,
 * "provisional" when the kernel marks it so). Never derived from list order;
 * a model without a served rank shows "—". */
export function rankText(model: Pick<ReleaseModel, "rank">): string {
  const rank = model.rank;
  if (!rank) return "—";
  return rankLabel(rank.provisional, rank.low, rank.high);
}

/** "1 full-request timeout" / "83 full-request timeouts". */
export function fullTimeoutsText(count: number): string {
  return `${count} full-request timeout${count === 1 ? "" : "s"}`;
}

/** Label for a release's git ref: a HISTORICAL record predates the ref that
 * carries its files, so it is not "frozen" by it. */
export function repositoryRefLabel(status: ReleaseStatus): string {
  return status === "HISTORICAL" ? "Evidence pinned at" : "Frozen git ref";
}

/** Label for a release's date. A HISTORICAL record was never released as a
 * benchmark; its date is the last recorded run. */
export function releaseDateLabel(status: ReleaseStatus): string {
  return status === "HISTORICAL" ? "Last recorded run" : "Released";
}

/** The served ranking-method sentence without its parenthesised file
 * references, for a plain-language description. The full text (with paths)
 * stays on the methodology page. */
export function plainRankingText(method: string): string {
  return method
    .replace(/\s*\([^()]*\)/g, "")
    .replace(/\s+([,.;])/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

/** One-line summary of a task-matrix cell for a screen-reader announcement:
 * "escape-html 1.0.1 · Qwen3.6 27B: 0 of 5 passed, Wilson 0.0–43.4%,
 * 5 timeouts (0 full)". Every figure is a served value. */
export function cellSummaryText(
  taskLabel: string,
  modelName: string,
  result: ReleaseTaskResult | undefined,
): string {
  const head = `${taskLabel} · ${modelName}`;
  if (!result || !result.evidence)
    return `${head}: ${result?.note ?? "no evidence"}`;
  const parts: string[] = [];
  parts.push(
    result.passes !== undefined && result.runs !== undefined
      ? `${result.passes} of ${result.runs} passed`
      : "passes not recorded",
  );
  if (result.wilson_low !== undefined && result.wilson_high !== undefined)
    parts.push(`Wilson ${intervalText(result.wilson_low, result.wilson_high)}`);
  else if (result.pass_rate !== undefined)
    parts.push(`pass rate ${pct(result.pass_rate, 1)}`);
  if (result.timeouts !== undefined) {
    const noun = result.timeouts === 1 ? "timeout" : "timeouts";
    parts.push(
      result.request_timeout_hits !== undefined
        ? `${result.timeouts} ${noun} (${result.request_timeout_hits} full)`
        : `${result.timeouts} ${noun}`,
    );
  }
  return `${head}: ${parts.join(", ")}`;
}
