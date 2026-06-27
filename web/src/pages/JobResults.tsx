import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";

// Results explorer scoped to one job. The job's run group (params.name) is the
// agent label in the store, so we surface:
//   - the leaderboard scoped to each evaluated task (server-ranked)
//   - the per (task, idx) run-detail links via the job-scoped run route
// All numbers come from the read-only API; nothing is recomputed here.
export function JobResults() {
  const { jobId = "" } = useParams();
  const job = useAsync((s) => api.job(jobId, s), [jobId]);

  if (job.loading) return <Loading label="Loading job results…" />;
  if (job.error) return <ErrorState error={job.error} onRetry={job.reload} />;

  const j = job.data!;
  const agent = j.params.name || j.params.model;

  return (
    <div>
      <h1 className="page-title">Results · job {j.id.slice(0, 8)}</h1>
      <p className="page-subtitle">
        Agent label <code>{agent}</code> · {j.params.tasks.length} tasks ×{" "}
        {j.params.repeats} repeats · {j.counters.completed_runs}/
        {j.counters.total_runs} runs completed.
      </p>
      <CaveatBanner />

      <div className="toolbar">
        <Link className="btn ghost" to={`/jobs/${encodeURIComponent(j.id)}`}>
          ← back to monitor
        </Link>
        <Link className="btn ghost" to={`/agent/${encodeURIComponent(agent)}`}>
          agent profile
        </Link>
        <Link className="btn ghost" to="/leaderboard">
          leaderboard
        </Link>
      </div>

      <div className="panel">
        <h2>Runs by task</h2>
        <p className="note muted">
          Each cell links to the global aggregate; each repeat opens the
          job-scoped run detail (avoids idx collisions across jobs).
        </p>
        <table className="data">
          <thead>
            <tr>
              <th>task</th>
              <th>cell (global)</th>
              <th>repeats</th>
            </tr>
          </thead>
          <tbody>
            {j.params.tasks.map((taskId) => (
              <tr key={taskId}>
                <td>
                  <Link to={`/task/${encodeURIComponent(taskId)}`}>{taskId}</Link>
                </td>
                <td>
                  <Link
                    to={`/cell/${encodeURIComponent(agent)}/${encodeURIComponent(taskId)}`}
                  >
                    open cell →
                  </Link>
                </td>
                <td>
                  <div className="row-actions" style={{ flexWrap: "wrap" }}>
                    {Array.from({ length: j.params.repeats }).map((_, i) => (
                      <Link
                        key={i}
                        className="badge"
                        to={`/jobs/${encodeURIComponent(j.id)}/runs/${encodeURIComponent(taskId)}/${i}`}
                      >
                        #{i}
                      </Link>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
