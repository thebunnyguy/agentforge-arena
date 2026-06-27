// Display-only helpers. The implementation plan explicitly allows:
//   - formatting percentages
//   - scaling an already-returned value onto a pixel bar
//   - sort/filter for display only
// It forbids any statistic computation (Wilson, pass@k, ranking, mean/std,
// domain pooling, Kish n). NOTHING in this file derives a statistic; every
// function takes a server-provided number and only formats/positions it.

export function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function fixed(value: number, digits = 3): string {
  return value.toFixed(digits);
}

// Position an already-computed [0,1] value on a 0..width pixel track.
export function toPx(value01: number, width: number): number {
  const clamped = Math.max(0, Math.min(1, value01));
  return clamped * width;
}

export function rankLabel(
  provisional: boolean,
  rankLow: number | null,
  rankHigh: number | null,
): string {
  if (provisional || rankLow === null || rankHigh === null) return "provisional";
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
      return "VOID (infra)";
    default:
      return status.toUpperCase();
  }
}

export function captureLabel(state: string): string {
  switch (state) {
    case "captured":
      return "captured";
    case "synthetic":
      return "synthetic";
    case "not_captured":
    default:
      return "not captured";
  }
}

export function jobStatusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function durationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
