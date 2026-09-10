import type { BackendKind, BackendVerifyResponse } from "../api/types";

export function verificationKey(kind: BackendKind, baseUrl: string): string {
  return `${kind}|${baseUrl.trim()}`;
}

export function hasVerifiedModel(
  response: BackendVerifyResponse | null,
  verifiedKey: string | null,
  requestKey: string,
  model: string,
): boolean {
  return (
    response?.ok === true &&
    verifiedKey === requestKey &&
    response.models.includes(model)
  );
}

export function validEvaluationParams(values: {
  repeats: number | "";
  baseSeed: number | "";
  temperature: number | "";
  timeout: number | "";
}): boolean {
  return (
    typeof values.repeats === "number" &&
    Number.isInteger(values.repeats) &&
    values.repeats >= 1 &&
    typeof values.baseSeed === "number" &&
    Number.isInteger(values.baseSeed) &&
    typeof values.temperature === "number" &&
    Number.isFinite(values.temperature) &&
    values.temperature >= 0 &&
    typeof values.timeout === "number" &&
    Number.isInteger(values.timeout) &&
    values.timeout >= 1
  );
}
