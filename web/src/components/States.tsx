import type { ReactNode } from "react";
import { AlertTriangle, LoaderCircle, RefreshCw } from "lucide-react";
import { ApiRequestError } from "../api/client";

export function Loading({ label = "Loading evidence…" }: { label?: string }) {
  return (
    <div className="state-card" aria-live="polite">
      <LoaderCircle className="loading-icon" size={22} aria-hidden="true" />
      <strong>{label}</strong>
      <span className="note muted">Reading the local evidence store.</span>
    </div>
  );
}

export function SkeletonRows({
  rows = 5,
  cols = 4,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="skeleton-table" aria-label="Loading table" role="status">
      {Array.from({ length: rows }).map((_, row) => (
        <div className="skeleton-row" key={row}>
          {Array.from({ length: cols }).map((__, col) => (
            <div
              className={`skeleton skeleton-cell skeleton-cell-${(col % 3) + 1}`}
              key={col}
            />
          ))}
        </div>
      ))}
    </div>
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
    <div className="state-card state-error" role="alert">
      <AlertTriangle size={22} aria-hidden="true" />
      <h3>
        {isUnreachable
          ? "Local API unavailable"
          : isNotFound
            ? "Evidence not found"
            : "Could not load this view"}
      </h3>
      <p>
        {isUnreachable
          ? "Start the AgentForge Arena API, then try again."
          : error.message}
      </p>
      {isUnreachable && (
        <code className="command-hint">python3 afa_app.py</code>
      )}
      {onRetry && (
        <button className="btn btn-secondary" onClick={onRetry} type="button">
          <RefreshCw size={15} aria-hidden="true" />
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state-card">
      <h3>{title}</h3>
      {children}
      {action && <div className="state-action">{action}</div>}
    </div>
  );
}
