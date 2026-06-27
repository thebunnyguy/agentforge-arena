import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { ErrorState, Loading } from "../components/States";

export function Tasks() {
  const meta = useAsync((s) => api.meta(s), []);
  if (meta.loading) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;

  return (
    <div>
      <h1 className="page-title">Tasks</h1>
      <p className="page-subtitle">Benchmark task pack present in the store.</p>
      <div className="panel">
        <table className="data">
          <thead>
            <tr>
              <th>task</th>
              <th>version</th>
              <th>domains</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {meta.data!.tasks.map((t) => (
              <tr key={t.task_id}>
                <td>
                  <Link to={`/task/${encodeURIComponent(t.task_id)}`}>{t.task_id}</Link>
                </td>
                <td className="mono">{t.current_version ?? "—"}</td>
                <td>
                  {t.domains && t.domains.length > 0
                    ? t.domains
                        .map((d) => `${d.domain} (${d.weight})`)
                        .join(", ")
                    : "—"}
                </td>
                <td>
                  <Link to={`/leaderboard`}>rank by this task →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
