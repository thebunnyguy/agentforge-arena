import { ApiRequestError } from "../api/client";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state-card">
      <div
        className="skeleton"
        style={{ height: 16, width: 180, margin: "0 auto 12px" }}
      />
      <div>{label}</div>
    </div>
  );
}

export function SkeletonRows({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <table className="data">
      <tbody>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r}>
            {Array.from({ length: cols }).map((__, c) => (
              <td key={c}>
                <div className="skeleton" style={{ height: 14, width: "70%" }} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: Error;
  onRetry?: () => void;
}) {
  const isUnreachable = error instanceof ApiRequestError && error.status === 0;
  const isNotFound = error instanceof ApiRequestError && error.status === 404;

  return (
    <div className="state-card error">
      {isUnreachable ? (
        <>
          <h3>Backend unreachable</h3>
          <p>
            The local API server isn't responding. Make sure the AgentForge Arena
            API is running and reachable.
          </p>
          <p className="mono" style={{ fontSize: 12 }}>
            uvicorn afa_api.main:app --reload
          </p>
        </>
      ) : isNotFound ? (
        <>
          <h3>Not found</h3>
          <p>{error.message}</p>
        </>
      ) : (
        <>
          <h3>Something went wrong</h3>
          <p>{error.message}</p>
        </>
      )}
      {onRetry && (
        <button className="btn secondary" onClick={onRetry} style={{ marginTop: 12 }}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="state-card">
      <h3>{title}</h3>
      {children}
    </div>
  );
}
