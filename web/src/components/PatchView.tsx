import { FileCode2 } from "lucide-react";
import type { CaptureState } from "../api/types";

export function PatchView({
  patch,
  captureState,
}: {
  patch: string | null;
  captureState: CaptureState;
}) {
  if (captureState === "synthetic") {
    return (
      <EvidenceMissing
        title="Synthetic baseline"
        detail="No real agent patch exists for this deterministic reference row."
      />
    );
  }
  if (patch === null || captureState === "not_captured") {
    return (
      <EvidenceMissing
        title="Patch not captured"
        detail="This legacy run predates patch capture. Its score primitives remain available, but the source diff does not."
      />
    );
  }
  if (patch.trim() === "") {
    return (
      <EvidenceMissing
        title="Empty diff"
        detail="The run produced no changed lines."
      />
    );
  }

  return (
    <div className="diff-shell">
      <div className="diff-toolbar">
        <span className="diff-file">
          <FileCode2 size={15} aria-hidden="true" /> unified diff
        </span>
        <span className="note muted">captured artifact</span>
      </div>
      <pre className="patch" tabIndex={0}>
        {patch.split("\n").map((line, index) => {
          let className = "";
          if (line.startsWith("+") && !line.startsWith("+++"))
            className = "add";
          else if (line.startsWith("-") && !line.startsWith("---"))
            className = "del";
          else if (line.startsWith("@@")) className = "hunk";
          return (
            <span
              className={className}
              key={`${index}-${line}`}
            >{`${line}\n`}</span>
          );
        })}
      </pre>
    </div>
  );
}

function EvidenceMissing({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="evidence-missing">
      <FileCode2 size={20} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}
