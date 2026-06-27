import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import { formatDate, jobStatusLabel } from "../lib/format";

function jobBadgeClass(status: string): string {
  switch (status) {
    case "succeeded":
      return "good";
    case "failed":
      return "bad";
    case "canceled":
      return "warn";
    case "running":
      return "void";
    default:
      return "";
  }
}

export function Jobs() {
  const jobs = useAsync((s) => api.jobs(s), []);

  return (
    <div>
      <h1 className="page-title">Jobs</h1>
      <p className="page-subtitle">Evaluation job history.</p>
      <CaveatBanner />

      <div className="toolbar">
        <Link className="btn" to="/new">
          + New evaluation
        </Link>
        <button className="btn ghost" onClick={jobs.reload}>
          Refresh
        </button>
      </div>

      <div className="panel">
        {jobs.loading ? (
          <Loading />
        ) : jobs.error ? (
          <ErrorState error={jobs.error} onRetry={jobs.reload} />
        ) : jobs.data!.jobs.length === 0 ? (
          <p className="note muted">
            No jobs yet. <Link to="/new">Create one →</Link>
          </p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>job</th>
                <th>name</th>
                <th>backend</th>
                <th>status</th>
                <th className="num">progress</th>
                <th className="num">pass / void / fail</th>
                <th>created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.data!.jobs.map((j) => (
                <tr key={j.id}>
                  <td className="mono">
                    <Link to={`/jobs/${encodeURIComponent(j.id)}`}>
                      {j.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{j.params.name || j.params.model}</td>
                  <td>{j.params.backend.kind}</td>
                  <td>
                    <span className={`badge ${jobBadgeClass(j.status)}`}>
                      {jobStatusLabel(j.status)}
                    </span>
                  </td>
                  <td className="num">
                    {j.counters.completed_runs}/{j.counters.total_runs}
                  </td>
                  <td className="num">
                    {j.counters.passed_runs} / {j.counters.voided_runs} /{" "}
                    {j.counters.failed_runs}
                  </td>
                  <td>{formatDate(j.created_at)}</td>
                  <td>
                    <Link to={`/jobs/${encodeURIComponent(j.id)}`}>open →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
