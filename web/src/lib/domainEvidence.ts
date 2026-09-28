// How the live UI presents one server-returned domain score. Pure: it reads
// the kernel's own fields and computes no statistic.
//
// The server's `displayable` flag stays the only authority on the display
// threshold (afa_kernel.domains: at least 5 tasks AND 25 runs). A domain below
// it that still has current evidence is shown as PROVISIONAL, with its value
// and its (wide) Wilson interval, never as a comparable score and never in an
// overall number. A domain with no valid runs carries the kernel's degenerate
// placeholder (rate 0, interval [0, 1]); that is absence of evidence, not 0%.
import type { DomainScore } from "../api/types";

/** Mirrors afa_kernel.domains MIN_TASKS_DISPLAY / MIN_RUNS_DISPLAY, for wording only. */
export const DOMAIN_MIN_TASKS = 5;
export const DOMAIN_MIN_RUNS = 25;

export type DomainEvidenceState = "displayable" | "provisional" | "none";

export function domainEvidenceState(domain: DomainScore): DomainEvidenceState {
  if (domain.displayable) return "displayable";
  return domain.n_tasks > 0 && domain.n_runs > 0 ? "provisional" : "none";
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** Why a domain is provisional, in the kernel's own counts. */
export function provisionalReason(domain: DomainScore): string {
  return `${plural(domain.n_tasks, "current task")} and ${plural(domain.n_runs, "run")}; the display threshold is ${DOMAIN_MIN_TASKS} tasks and ${DOMAIN_MIN_RUNS} runs`;
}

export const PROVISIONAL_DOMAIN_NOTE =
  "Provisional domains have current evidence below the display threshold of 5 tasks and 25 runs. They are shown with their wider intervals for inspection; they are not comparable with displayable domains and never enter an overall score.";
