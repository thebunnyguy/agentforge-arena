import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { EvidenceScope } from "../api/types";

const SCOPES: ReadonlySet<string> = new Set([
  "benchmark",
  "real",
  "synthetic",
  "all",
]);

export function isEvidenceScope(value: string | null): value is EvidenceScope {
  return value !== null && SCOPES.has(value);
}

/**
 * Evidence scope bound to the URL (?evidence=). Default "benchmark"
 * (real + legacy, current version only). Other query params are preserved.
 */
export function useEvidenceScope(): [
  EvidenceScope,
  (next: EvidenceScope) => void,
] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("evidence");
  const scope: EvidenceScope = isEvidenceScope(raw) ? raw : "benchmark";
  const setScope = useCallback(
    (next: EvidenceScope) => {
      setParams(
        (previous) => {
          const merged = new URLSearchParams(previous);
          if (next === "benchmark") merged.delete("evidence");
          else merged.set("evidence", next);
          return merged;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return [scope, setScope];
}

/**
 * Query string for in-app links so a drill-down keeps the reader's evidence
 * scope and (optionally) a selected version. Returns "" for defaults.
 */
export function linkQuery(
  scope: EvidenceScope | null | undefined,
  version?: string | null,
): string {
  const params = new URLSearchParams();
  if (version) params.set("version", version);
  if (scope && scope !== "benchmark") params.set("evidence", scope);
  const text = params.toString();
  return text ? `?${text}` : "";
}
