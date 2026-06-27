import type { CaptureState, RunStatus } from "../api/types";
import { captureLabel, fixed, statusLabel } from "../lib/format";

export function StatusBadge({ status }: { status: RunStatus }) {
  const cls =
    status === "valid"
      ? "good"
      : status === "infra_failure"
        ? "void"
        : "bad";
  return <span className={`badge ${cls}`}>{statusLabel(status)}</span>;
}

export function CaptureBadge({ state }: { state: CaptureState }) {
  const cls =
    state === "captured" ? "good" : state === "synthetic" ? "synthetic" : "warn";
  return <span className={`badge ${cls}`}>{captureLabel(state)}</span>;
}

// Score S in [0,1]; the value is server-provided, we only format + colour it.
export function ScoreBadge({ score }: { score: number }) {
  const cls = score >= 0.999 ? "good" : score <= 0.001 ? "bad" : "warn";
  return <span className={`badge ${cls} score-badge`}>{fixed(score, 3)}</span>;
}

export function PassBadge({ pass }: { pass: boolean }) {
  return (
    <span className={`badge ${pass ? "good" : "bad"}`}>{pass ? "PASS" : "fail"}</span>
  );
}

export function ProvisionalBadge() {
  return <span className="badge prov">provisional</span>;
}

export function GateBadge({ g }: { g: number }) {
  return <span className={`badge ${g === 1 ? "good" : "bad"}`}>G={g}</span>;
}
