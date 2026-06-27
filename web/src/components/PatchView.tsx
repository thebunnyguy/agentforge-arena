import type { CaptureState } from "../api/types";

// Renders a unified-diff patch string with simple +/-/@@ colouring. When the
// artifact wasn't captured (legacy rows) or is synthetic, render the honest
// placeholder instead of a fake patch.
export function PatchView({
  patch,
  captureState,
}: {
  patch: string | null;
  captureState: CaptureState;
}) {
  if (captureState === "synthetic") {
    return (
      <div className="note muted">
        Synthetic baseline — no real agent patch exists for this run.
      </div>
    );
  }
  if (patch === null || captureState === "not_captured") {
    return (
      <div className="note muted">
        Patch text not captured for this run (legacy row predating diff capture).
      </div>
    );
  }
  if (patch.trim() === "") {
    return <div className="note muted">Empty diff (no changes produced).</div>;
  }

  const lines = patch.split("\n");
  return (
    <pre className="patch">
      {lines.map((line, i) => {
        let cls = "";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
        else if (line.startsWith("@@")) cls = "hunk";
        return (
          <span key={i} className={cls}>
            {line + "\n"}
          </span>
        );
      })}
    </pre>
  );
}
