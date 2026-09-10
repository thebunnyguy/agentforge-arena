import { Check, CircleDashed, CircleX, Pause, Sparkles } from "lucide-react";
import type { CaptureState, JobStatus, RunStatus } from "../api/types";
import {
  captureLabel,
  fixed,
  jobStatusLabel,
  statusLabel,
} from "../lib/format";

export function StatusBadge({ status }: { status: RunStatus }) {
  const cls =
    status === "valid" ? "good" : status === "infra_failure" ? "void" : "bad";
  const Icon =
    status === "valid"
      ? Check
      : status === "infra_failure"
        ? CircleDashed
        : CircleX;
  return (
    <span className={`badge ${cls}`}>
      <Icon size={12} aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}

export function CaptureBadge({ state }: { state: CaptureState }) {
  const cls =
    state === "captured"
      ? "good"
      : state === "synthetic"
        ? "synthetic"
        : "warn";
  return (
    <span className={`badge ${cls}`}>
      {state === "synthetic" ? (
        <Sparkles size={12} aria-hidden="true" />
      ) : (
        <CircleDashed size={12} aria-hidden="true" />
      )}
      {captureLabel(state)}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const cls = score >= 0.999 ? "good" : score <= 0.001 ? "bad" : "warn";
  return <span className={`badge ${cls} score-badge`}>{fixed(score, 3)}</span>;
}

export function RunOutcomeBadge({
  status,
  functionalPass,
}: {
  status: RunStatus;
  functionalPass: boolean;
}) {
  if (status === "infra_failure")
    return (
      <span className="badge void">
        <CircleDashed size={12} aria-hidden="true" />
        VOID · INFRA
      </span>
    );
  return <PassBadge pass={functionalPass} />;
}

export function PassBadge({ pass }: { pass: boolean }) {
  return (
    <span className={`badge ${pass ? "good" : "bad"}`}>
      {pass ? (
        <Check size={12} aria-hidden="true" />
      ) : (
        <CircleX size={12} aria-hidden="true" />
      )}
      {pass ? "PASS" : "FAIL"}
    </span>
  );
}

export function ProvisionalBadge() {
  return <span className="badge prov">provisional</span>;
}

export function GateBadge({ g }: { g: number }) {
  return <span className={`badge ${g === 1 ? "good" : "bad"}`}>G = {g}</span>;
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const cls =
    status === "succeeded"
      ? "good"
      : status === "failed"
        ? "bad"
        : status === "canceled"
          ? "warn"
          : status === "running"
            ? "void"
            : "neutral";
  const Icon =
    status === "succeeded"
      ? Check
      : status === "failed"
        ? CircleX
        : status === "canceled"
          ? Pause
          : status === "running"
            ? CircleDashed
            : CircleDashed;
  return (
    <span className={`badge ${cls}`}>
      <Icon size={12} aria-hidden="true" />
      {jobStatusLabel(status)}
    </span>
  );
}

export function BooleanBadge({
  value,
  trueLabel = "yes",
  falseLabel = "no",
}: {
  value: boolean;
  trueLabel?: string;
  falseLabel?: string;
}) {
  return (
    <span className={`badge ${value ? "good" : "neutral"}`}>
      {value ? trueLabel : falseLabel}
    </span>
  );
}
