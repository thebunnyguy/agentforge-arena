import type { ReactNode } from "react";
import { ShieldAlert } from "lucide-react";

export function CaveatBanner({ caveat }: { caveat?: string | null }) {
  return (
    <div className="caveat" role="note">
      <ShieldAlert size={17} aria-hidden="true" />
      <div>
        <strong>Trusted-local benchmark.</strong>{" "}
        {caveat ||
          "Single-user local tool. Agent code runs with host privileges via LocalSandbox; there is no untrusted-agent isolation or security boundary. Numbers come from the frozen scoring kernel and are rendered as returned."}
      </div>
    </div>
  );
}

export function InlineCaveat({ children }: { children: ReactNode }) {
  return <p className="note muted">{children}</p>;
}
