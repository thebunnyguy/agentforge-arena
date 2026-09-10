// Display-only helpers. Benchmark values are produced by the API/kernel; these
// helpers only format them or map an already-served value to screen geometry.

export function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function fixed(value: number, digits = 3): string {
  return value.toFixed(digits);
}

export function count(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(
    value,
  );
}

export function toPx(value01: number, width: number): number {
  const clamped = Math.max(0, Math.min(1, value01));
  return clamped * width;
}

export function rankLabel(
  provisional: boolean,
  rankLow: number | null,
  rankHigh: number | null,
): string {
  if (provisional || rankLow === null || rankHigh === null)
    return "provisional";
  if (rankLow === rankHigh) return String(rankLow);
  return `${rankLow}–${rankHigh}`;
}

export function statusLabel(status: string): string {
  switch (status) {
    case "valid":
      return "VALID";
    case "timeout":
      return "TIMEOUT";
    case "agent_error":
      return "AGENT ERROR";
    case "infra_failure":
      return "VOID · INFRA";
    default:
      return status.replace(/_/g, " ").toUpperCase();
  }
}

export function captureLabel(state: string): string {
  switch (state) {
    case "captured":
      return "captured";
    case "synthetic":
      return "synthetic baseline";
    default:
      return "not captured";
  }
}

export function jobStatusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(
    value.includes("T") ? value : `${value.replace(" ", "T")}Z`,
  );
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatRelativeDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(
    value.includes("T") ? value : `${value.replace(" ", "T")}Z`,
  );
  if (Number.isNaN(date.getTime())) return value;
  const delta = Date.now() - date.getTime();
  const minutes = Math.round(delta / 60000);
  if (Math.abs(minutes) < 1) return "just now";
  if (Math.abs(minutes) < 60)
    return `${Math.abs(minutes)}m ${minutes >= 0 ? "ago" : "from now"}`;
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24)
    return `${Math.abs(hours)}h ${hours >= 0 ? "ago" : "from now"}`;
  const days = Math.round(hours / 24);
  return `${Math.abs(days)}d ${days >= 0 ? "ago" : "from now"}`;
}

export function durationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

export function jobDuration(
  started: string | null | undefined,
  finished: string | null | undefined,
): string {
  if (!started) return "—";
  const start = new Date(
    started.includes("T") ? started : `${started.replace(" ", "T")}Z`,
  );
  const end = finished
    ? new Date(
        finished.includes("T") ? finished : `${finished.replace(" ", "T")}Z`,
      )
    : new Date();
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "—";
  return durationMs(Math.max(0, end.getTime() - start.getTime()));
}

export function backendLabel(kind: string): string {
  switch (kind) {
    case "openai_compat":
      return "OpenAI-compatible";
    case "ollama":
      return "Ollama";
    case "mock":
      return "Mock";
    default:
      return kind;
  }
}

export function taskScope(tasks: number, repeats: number): string {
  return `${tasks} task${tasks === 1 ? "" : "s"} × ${repeats} repeat${repeats === 1 ? "" : "s"}`;
}
