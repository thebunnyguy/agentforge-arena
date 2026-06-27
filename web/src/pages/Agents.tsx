import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { ErrorState, Loading } from "../components/States";

export function Agents() {
  const meta = useAsync((s) => api.meta(s), []);
  const lb = useAsync((s) => api.leaderboard(null, s), []);

  if (meta.loading) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const nByAgent = new Map(lb.data?.entries.map((e) => [e.agent, e.n]) ?? []);

  return (
    <div>
      <h1 className="page-title">Agents</h1>
      <p className="page-subtitle">Every agent present in the local run store.</p>
      <div className="panel">
        <table className="data">
          <thead>
            <tr>
              <th>agent</th>
              <th className="num">valid runs (pooled)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {meta.data!.models.map((a: string) => (
              <tr key={a}>
                <td>
                  <Link to={`/agent/${encodeURIComponent(a)}`}>{a}</Link>
                </td>
                <td className="num">{nByAgent.get(a) ?? "—"}</td>
                <td>
                  <Link to={`/agent/${encodeURIComponent(a)}`}>domain profile →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
