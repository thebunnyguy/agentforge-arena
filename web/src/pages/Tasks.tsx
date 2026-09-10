import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, EmptyState, Loading } from "../components/States";
import { PageHeader, Panel, SectionHeader } from "../components/Primitives";

export function Tasks() {
  const meta = useAsync((signal) => api.meta(signal), []);
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("");
  const tasks = useMemo(() => {
    const all = meta.data?.tasks ?? [];
    const needle = query.trim().toLowerCase();
    return all.filter((task) => {
      const matchesText =
        !needle ||
        task.task_id.toLowerCase().includes(needle) ||
        (task.activity ?? "").toLowerCase().includes(needle);
      const matchesDomain =
        !domain || task.domains.some((tag) => tag.domain === domain);
      return matchesText && matchesDomain;
    });
  }, [meta.data, query, domain]);
  const domains = [
    ...new Set(
      (meta.data?.tasks ?? []).flatMap((task) =>
        task.domains.map((tag) => tag.domain),
      ),
    ),
  ].sort();

  if (meta.loading) return <Loading label="Loading task pack…" />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;

  return (
    <div>
      <PageHeader
        eyebrow="Analyze"
        title="Tasks"
        description="The benchmark pack is the experimental surface. Versions and domains stay visible so comparisons have context."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <Panel>
        <SectionHeader
          title="Task pack"
          description={`${tasks.length} of ${meta.data!.tasks.length} tasks shown.`}
        />
        <div className="toolbar">
          <div className="search-field">
            <Search size={15} aria-hidden="true" />
            <input
              aria-label="Search tasks"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search task IDs or activities…"
            />
          </div>
          <select
            aria-label="Filter by domain"
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
          >
            <option value="">All domains</option>
            {domains.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        {tasks.length === 0 ? (
          <EmptyState title="No matching tasks">
            <p>Clear the search or domain filter to see the full pack.</p>
          </EmptyState>
        ) : (
          <div className="table-scroll" tabIndex={0}>
            <table className="data">
              <thead>
                <tr>
                  <th>task</th>
                  <th>activity</th>
                  <th>difficulty</th>
                  <th>scale</th>
                  <th>domains</th>
                  <th>version</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.task_id}>
                    <td className="primary-cell">
                      <Link
                        className="mono"
                        to={`/task/${encodeURIComponent(task.task_id)}`}
                      >
                        {task.task_id}
                      </Link>
                    </td>
                    <td>{task.activity ?? "—"}</td>
                    <td className="mono">{task.difficulty ?? "—"}</td>
                    <td className="mono">{task.scale ?? "—"}</td>
                    <td>
                      {task.domains.length ? (
                        <div className="tag-list">
                          {task.domains.map((tag) => (
                            <span
                              className="tag"
                              key={`${task.task_id}-${tag.domain}`}
                            >
                              {tag.domain} · {tag.weight}
                            </span>
                          ))}
                        </div>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="mono">{task.current_version ?? "—"}</td>
                    <td>
                      <Link
                        className="link-arrow"
                        to={`/task/${encodeURIComponent(task.task_id)}`}
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
