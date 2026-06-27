import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <div className="state-card">
      <h2>Page not found</h2>
      <p className="note muted">
        This route doesn't exist, or the agent/task/run/job couldn't be resolved.
      </p>
      <Link className="btn secondary" to="/" style={{ marginTop: 12 }}>
        Back to overview
      </Link>
    </div>
  );
}
