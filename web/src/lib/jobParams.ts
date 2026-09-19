// The ONE reader of Job.params. Persisted evaluation parameters can be
// unverifiable (params === null, params_status "unverifiable"); every consumer
// goes through jobParamsView() so nothing dereferences null.
//
// Old-shape payloads (test fixtures, older servers) carry `params` but no
// `params_status`: a non-null params object is treated as available.

import type {
  BackendKind,
  Job,
  JobEvidenceClass,
  JobParams,
} from "../api/types";

export type JobParamsView =
  | {
      available: true;
      params: JobParams;
      model: string;
      name: string | null;
      backendKind: BackendKind;
      tasks: string[];
      repeats: number;
    }
  | {
      available: false;
      params: null;
      reason: string;
    };

export const PARAMS_UNAVAILABLE_TITLE = "Evaluation parameters unavailable";
const DEFAULT_REASON =
  "The persisted evaluation parameters could not be verified.";

/** The server reason as a complete sentence (no doubled or missing period). */
export function reasonSentence(reason: string): string {
  const trimmed = reason.trim().replace(/[.\s]+$/, "");
  return `${trimmed}.`;
}

export function jobParamsView(
  job: Pick<Job, "params" | "params_status" | "params_error">,
): JobParamsView {
  const params = job.params ?? null;
  if (params === null || job.params_status === "unverifiable") {
    return {
      available: false,
      params: null,
      reason: job.params_error || DEFAULT_REASON,
    };
  }
  return {
    available: true,
    params,
    model: params.model ?? "",
    name: params.name ?? null,
    backendKind: params.backend?.kind,
    tasks: Array.isArray(params.tasks) ? params.tasks : [],
    repeats: typeof params.repeats === "number" ? params.repeats : 0,
  };
}

/** Effective evidence class: the server value, else derived from the backend. */
export function jobEvidenceClass(
  job: Pick<Job, "params" | "evidence_class" | "backend_kind">,
): JobEvidenceClass {
  if (job.evidence_class) return job.evidence_class;
  const kind = job.backend_kind ?? job.params?.backend?.kind ?? null;
  if (kind === "mock") return "synthetic";
  if (kind === "ollama" || kind === "openai_compat") return "real";
  return "unknown";
}
