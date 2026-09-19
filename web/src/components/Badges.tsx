import {
  Check,
  CircleDashed,
  CircleX,
  History,
  Pause,
  Sparkles,
} from "lucide-react";
import type {
  CaptureState,
  EvidenceClass,
  JobEvidenceClass,
  JobStatus,
  RunStatus,
} from "../api/types";
import {
  captureLabel,
  evidenceClassHelp,
  evidenceClassLabel,
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
  // "historical_only" must never read as captured current evidence.
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

// Server enum -> text badge. Never colour alone: every state has its own word.
export type VersionBadgeStatus =
  | "current"
  | "historical"
  | "historical_only"
  | "missing"
  | "none"
  | "synthetic"
  | "not_captured";

export function VersionStatusBadge({
  status,
}: {
  status: VersionBadgeStatus | string | null | undefined;
}) {
  switch (status) {
    case "current":
      return (
        <span className="badge good">
          <Check size={12} aria-hidden="true" />
          CURRENT
        </span>
      );
    case "historical":
      return (
        <span className="badge warn">
          <History size={12} aria-hidden="true" />
          HISTORICAL
        </span>
      );
    case "historical_only":
      return (
        <span className="badge warn">
          <History size={12} aria-hidden="true" />
          HISTORICAL ONLY
        </span>
      );
    case "missing":
      return (
        <span className="badge warn">
          <CircleDashed size={12} aria-hidden="true" />
          MISSING CURRENT
        </span>
      );
    case "synthetic":
      return (
        <span className="badge synthetic">
          <Sparkles size={12} aria-hidden="true" />
          SYNTHETIC
        </span>
      );
    default:
      return (
        <span className="badge neutral">
          <CircleDashed size={12} aria-hidden="true" />
          NO EVIDENCE
        </span>
      );
  }
}

// The one phrase used everywhere a model lacks current-version evidence.
export function MissingCurrentEvidence({
  historicalAvailable = true,
  detail,
}: {
  historicalAvailable?: boolean;
  detail?: string;
}) {
  return (
    <span>
      <VersionStatusBadge status="missing" />
      <span className="missing-note">
        MISSING current evidence
        {historicalAvailable
          ? " - historical evidence available"
          : " - no evidence"}
        {detail ? ` ${detail}` : ""}
      </span>
    </span>
  );
}

// Provider provenance of a run/job. `long` spells out what "legacy" means.
export function EvidenceClassBadge({
  cls,
  backendKind,
  long = false,
}: {
  cls: EvidenceClass | JobEvidenceClass | string | null | undefined;
  backendKind?: string | null;
  long?: boolean;
}) {
  const tone =
    cls === "real"
      ? "good"
      : cls === "synthetic"
        ? "synthetic"
        : cls === "conflict"
          ? "bad"
          : cls === "legacy"
            ? "warn"
            : "neutral";
  const label = evidenceClassLabel(cls);
  const detail = long
    ? cls === "legacy"
      ? " · unknown provider"
      : cls === "synthetic"
        ? " · mock"
        : cls === "real" && backendKind
          ? ` · ${backendKind}`
          : ""
    : "";
  return (
    <span className={`badge ${tone}`} title={evidenceClassHelp(cls)}>
      {cls === "synthetic" && <Sparkles size={12} aria-hidden="true" />}
      {label.toUpperCase()}
      {detail}
    </span>
  );
}

// Evidence-class chip for an evaluation (job). Mock evidence is synthetic and
// is excluded from the default benchmark views.
export function JobEvidenceChip({
  cls,
  backendKind,
}: {
  cls: JobEvidenceClass | null | undefined;
  backendKind?: string | null;
}) {
  if (cls === "synthetic")
    return (
      <span className="badge synthetic badge-wrap">
        <Sparkles size={12} aria-hidden="true" />
        SYNTHETIC · mock - excluded from benchmark results
      </span>
    );
  if (cls === "real")
    return (
      <span className="badge good badge-wrap">
        REAL{backendKind ? ` · ${backendKind}` : ""}
      </span>
    );
  return <span className="badge neutral badge-wrap">PROVIDER UNKNOWN</span>;
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
