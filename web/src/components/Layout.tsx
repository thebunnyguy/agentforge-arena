import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAsync } from "../lib/useAsync";
import { api, API_BASE } from "../api/client";
import { formatDate } from "../lib/format";

const nav = [
  {
    section: "Explore",
    links: [
      { to: "/", label: "Overview", end: true },
      { to: "/leaderboard", label: "Leaderboard" },
      { to: "/agents", label: "Agents" },
      { to: "/tasks", label: "Tasks" },
      { to: "/runs", label: "Runs" },
      { to: "/methodology", label: "Methodology" },
    ],
  },
  {
    section: "Evaluate",
    links: [
      { to: "/new", label: "New evaluation" },
      { to: "/jobs", label: "Jobs" },
      { to: "/reports", label: "Reports" },
      { to: "/settings", label: "Settings" },
    ],
  },
];

function ConnPill() {
  const { data, error } = useAsync((s) => api.health(s), []);
  const ok = !!data?.stores_loaded && !error;
  return (
    <span className="conn-pill" title={error ? String(error.message) : "API healthy"}>
      <span className={`dot ${ok ? "ok" : error ? "bad" : ""}`} />
      {error ? "API unreachable" : ok ? "API connected" : "Connecting…"}
    </span>
  );
}

export function Layout() {
  const { data: meta } = useAsync((s) => api.meta(s), []);
  const location = useLocation();
  const obs = meta?.observability;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          AgentForge Arena
          <small>trusted-local benchmark</small>
        </div>
        {nav.map((group) => (
          <div key={group.section}>
            <div className="nav-section">{group.section}</div>
            {group.links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              >
                {l.label}
              </NavLink>
            ))}
          </div>
        ))}
        <div className="spacer" />
        <div className="nav-section">Status</div>
        <div style={{ padding: "4px 10px", fontSize: 12, color: "var(--text-faint)" }}>
          {meta ? (
            <>
              {obs?.total_runs ?? 0} runs · {meta.models.length} agents ·{" "}
              {meta.n_tasks} tasks
            </>
          ) : (
            "—"
          )}
        </div>
      </aside>

      <header className="topbar">
        <Breadcrumbs path={location.pathname} />
        <div className="spacer" />
        <ConnPill />
      </header>

      <main className="main">
        <Outlet />
      </main>

      <footer className="footer">
        <span>
          DB snapshot:{" "}
          {obs?.first_created_at
            ? `${formatDate(obs.first_created_at)} → ${formatDate(obs.last_created_at)}`
            : "—"}
        </span>
        <span>
          Patch coverage: {obs ? `${obs.runs_with_patch}/${obs.total_runs}` : "—"}
        </span>
        <span>API {API_BASE || "(same origin)"}</span>
        <span className="spacer" />
        <span>Trusted-local only · no untrusted-agent isolation</span>
      </footer>
    </div>
  );
}

// Lightweight breadcrumbs derived from the path. Display-only.
function Breadcrumbs({ path }: { path: string }) {
  const parts = path.split("/").filter(Boolean);
  if (parts.length === 0) {
    return <div className="breadcrumbs">Overview</div>;
  }
  const crumbs: { label: string; to: string }[] = [{ label: "Overview", to: "/" }];
  let acc = "";
  for (const p of parts) {
    acc += `/${p}`;
    crumbs.push({ label: decodeURIComponent(p), to: acc });
  }
  return (
    <div className="breadcrumbs">
      {crumbs.map((c, i) => (
        <span key={c.to}>
          {i > 0 && <span className="sep">/</span>}
          {i < crumbs.length - 1 ? <NavLink to={c.to}>{c.label}</NavLink> : <span>{c.label}</span>}
        </span>
      ))}
    </div>
  );
}
