import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { PageHeader, Panel } from "../Primitives";

// The benchmark pages are lazy chunks that carry the release datasets. This
// wrapper keeps the app shell independent of them: a slow chunk shows a
// status line, and a failed chunk or a dataset that fails validation shows an
// error panel on /benchmarks instead of unmounting the whole app. It imports
// nothing from the release registry.

class BenchmarkErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(
      "Benchmark page failed to render",
      error,
      info.componentStack,
    );
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="bench-page">
        <PageHeader
          eyebrow="Benchmark release"
          title="Benchmark release unavailable"
        />
        <Panel tone="bad">
          <p className="note">
            The benchmark release page could not be loaded. Its dataset may have
            failed validation, or the page bundle failed to download.
          </p>
          <p className="note mono bench-error-message">
            {error.message || String(error)}
          </p>
          <div className="row-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => window.location.reload()}
            >
              Reload the page
            </button>
            <Link className="btn btn-secondary" to="/">
              Back to the overview
            </Link>
          </div>
        </Panel>
      </div>
    );
  }
}

function BenchmarkLoading() {
  return (
    <div className="bench-page">
      <p className="note muted" role="status">
        Loading benchmark release…
      </p>
    </div>
  );
}

/** Suspense + error boundary for one lazily loaded benchmark page. Keyed by
 * path so an error on one URL does not stick to the next one. */
export function BenchmarkRoute({ children }: { children: ReactNode }) {
  const location = useLocation();
  return (
    <BenchmarkErrorBoundary key={location.pathname}>
      <Suspense fallback={<BenchmarkLoading />}>{children}</Suspense>
    </BenchmarkErrorBoundary>
  );
}
