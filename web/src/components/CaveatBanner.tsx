// Honesty element required on every relevant page (implementation plan §
// "Keep the app honest" + Phase 3 honesty elements). The app is a trusted-local
// single-user tool. LocalSandbox is NOT a security boundary; we never claim
// untrusted-agent isolation.
export function CaveatBanner({ caveat }: { caveat?: string | null }) {
  return (
    <div className="caveat">
      <strong>Trusted-local benchmark.</strong>{" "}
      {caveat ||
        "This is a single-user local tool. Agent code runs with host privileges via LocalSandbox — there is no untrusted-agent isolation or security boundary. All numbers are computed by the frozen scoring kernel and rendered as-is."}
    </div>
  );
}

export function InlineCaveat({ children }: { children: React.ReactNode }) {
  return <p className="note muted">{children}</p>;
}
