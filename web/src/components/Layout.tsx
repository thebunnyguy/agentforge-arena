import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  BookOpen,
  Bot,
  FileBarChart,
  History,
  Home,
  ListChecks,
  Menu,
  Plus,
  Settings as SettingsIcon,
  Trophy,
  X,
} from "lucide-react";
import { api, API_BASE } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { formatDate } from "../lib/format";
import { StatusDot } from "./Primitives";

const nav = [
  {
    section: "Home",
    links: [{ to: "/", label: "Overview", icon: Home, end: true }],
  },
  {
    section: "Evaluate",
    links: [
      { to: "/new", label: "New evaluation", icon: Plus },
      { to: "/jobs", label: "Evaluations", icon: History },
    ],
  },
  {
    section: "Analyze",
    links: [
      { to: "/leaderboard", label: "Leaderboard", icon: Trophy },
      { to: "/agents", label: "Agents", icon: Bot },
      { to: "/tasks", label: "Tasks", icon: ListChecks },
    ],
  },
  {
    section: "Tools",
    links: [{ to: "/reports", label: "Reports", icon: FileBarChart }],
  },
];

function ConnPill() {
  const { data, error } = useAsync((signal) => api.health(signal), []);
  const ready = !!data?.stores_loaded && !error;
  return (
    <span
      className="conn-pill"
      title={error ? error.message : "Local API status"}
    >
      <StatusDot
        label={
          error ? "API unavailable" : ready ? "Local API ready" : "Connecting"
        }
        tone={error ? "bad" : ready ? "good" : "neutral"}
        pulse={!error && !ready}
      />
    </span>
  );
}

function SidebarContents({ onNavigate }: { onNavigate?: () => void }) {
  const { data: meta } = useAsync((signal) => api.meta({}, signal), []);
  const obs = meta?.observability;
  return (
    <>
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          A
        </span>
        <span className="brand-copy">
          AgentForge Arena<small>local evaluation workstation</small>
        </span>
      </div>
      {nav.map((group) => (
        <div key={group.section}>
          <div className="nav-section">{group.section}</div>
          {group.links.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink
                key={link.to}
                to={link.to}
                end={"end" in link ? link.end : false}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `nav-link ${isActive ? "active" : ""}`
                }
              >
                <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
                <span>{link.label}</span>
              </NavLink>
            );
          })}
        </div>
      ))}
      <div className="spacer" />
      <NavLink to="/settings" onClick={onNavigate} className="nav-link">
        <SettingsIcon size={16} strokeWidth={1.8} aria-hidden="true" />
        <span>Settings</span>
      </NavLink>
      <NavLink to="/methodology" onClick={onNavigate} className="nav-link">
        <BookOpen size={16} strokeWidth={1.8} aria-hidden="true" />
        <span>Methodology</span>
      </NavLink>
      <div className="sidebar-status">
        <StatusDot label="Trusted local" tone="warn" />
        <div className="sidebar-count">
          {meta
            ? meta.current_benchmark
              ? `${meta.current_benchmark.current_runs} current / ${obs?.total_runs ?? 0} persisted runs · ${meta.current_benchmark.tasks_with_current_evidence}/${meta.current_benchmark.n_tasks} tasks with current evidence`
              : `${obs?.total_runs ?? 0} persisted runs · ${meta.n_tasks} tasks`
            : "Loading evidence store…"}
        </div>
      </div>
    </>
  );
}

export function Layout() {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const obsState = useAsync((signal) => api.meta({}, signal), []);
  const obs = obsState.data?.observability;

  useEffect(() => {
    setMobileOpen(false);
    window.scrollTo({ top: 0, behavior: "auto" });
    requestAnimationFrame(() =>
      document.getElementById("main-content")?.focus(),
    );
  }, [location.pathname]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (mobileOpen && !dialog.open) {
      restoreFocus.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      dialog.showModal();
      dialog.querySelector<HTMLElement>("button, a")?.focus();
    } else if (!mobileOpen && dialog.open) {
      dialog.close();
      restoreFocus.current?.focus();
      restoreFocus.current = null;
    }
    const trap = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = [
        ...dialog.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled])",
        ),
      ];
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", trap);
    return () => dialog.removeEventListener("keydown", trap);
  }, [mobileOpen]);

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside
        className="sidebar desktop-sidebar"
        aria-label="Primary navigation"
      >
        <SidebarContents />
      </aside>
      <dialog
        ref={dialogRef}
        className="mobile-nav-dialog"
        aria-label="Primary navigation"
        onCancel={(event) => {
          event.preventDefault();
          setMobileOpen(false);
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget) setMobileOpen(false);
        }}
      >
        <div className="mobile-dialog-header">
          <strong>Navigation</strong>
          <button
            className="mobile-menu"
            aria-label="Close navigation"
            type="button"
            onClick={() => setMobileOpen(false)}
          >
            <X size={17} />
          </button>
        </div>
        <aside className="sidebar dialog-sidebar">
          <SidebarContents onNavigate={() => setMobileOpen(false)} />
        </aside>
      </dialog>
      <header className="topbar">
        <button
          className="mobile-menu"
          aria-label="Open navigation"
          aria-haspopup="dialog"
          aria-expanded={mobileOpen}
          type="button"
          onClick={() => setMobileOpen(true)}
        >
          <Menu size={17} />
        </button>
        <Breadcrumbs path={location.pathname} />
        <div className="spacer" />
        <Link className="btn btn-small" to="/new">
          <Plus size={14} aria-hidden="true" /> New evaluation
        </Link>
        <ConnPill />
      </header>
      <main className="main" id="main-content" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        <span>
          Evidence window (all persisted runs):{" "}
          {obs?.first_created_at
            ? `${formatDate(obs.first_created_at)} → ${formatDate(obs.last_created_at)}`
            : "—"}
        </span>
        <span>
          Patch capture (all versions):{" "}
          {obs ? `${obs.runs_with_patch}/${obs.total_runs}` : "—"}
        </span>
        <span>API {API_BASE || "same origin"}</span>
        <span className="spacer" />
        <span>Trusted local · no untrusted-agent isolation</span>
      </footer>
    </div>
  );
}

function Breadcrumbs({ path }: { path: string }) {
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const crumbs: Array<{ label: string; to?: string }> = [
    { label: "Overview", to: "/" },
  ];
  const add = (label: string, to?: string) => crumbs.push({ label, to });
  if (parts[0] === "agent" && parts[1]) {
    add("Agents", "/agents");
    add(parts[1]);
  } else if (parts[0] === "task" && parts[1]) {
    add("Tasks", "/tasks");
    add(parts[1]);
  } else if (parts[0] === "cell" && parts[1] && parts[2]) {
    const agent = parts[1];
    const task = parts[2];
    add("Agents", "/agents");
    add(agent, `/agent/${encodeURIComponent(agent)}`);
    add("Tasks", "/tasks");
    add(task, `/task/${encodeURIComponent(task)}`);
    if (parts[3] === "run" && parts[4] !== undefined) add(`Run #${parts[4]}`);
    else add("Cell");
  } else if (parts[0] === "jobs" && parts[1]) {
    const jobId = parts[1];
    add("Evaluations", "/jobs");
    add(jobId, `/jobs/${encodeURIComponent(jobId)}`);
    if (parts[2] === "results") add("Results");
    else if (parts[2] === "runs" && parts[3] && parts[4] !== undefined) {
      add(parts[3], `/task/${encodeURIComponent(parts[3])}`);
      add(`Run #${parts[4]}`);
    }
  } else if (parts[0] === "runs") add("Leaderboard", "/leaderboard");
  else if (parts[0] === "leaderboard") add("Leaderboard");
  else if (parts[0] === "agents") add("Agents");
  else if (parts[0] === "tasks") add("Tasks");
  else if (parts[0] === "new") add("New evaluation");
  else if (parts[0] === "reports") add("Reports");
  else if (parts[0] === "settings") add("Settings");
  else if (parts[0] === "methodology") add("Methodology");
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      {crumbs.map((crumb, index) => (
        <span key={`${crumb.label}-${index}`}>
          {index > 0 && <span className="sep">/</span>}
          {crumb.to && index < crumbs.length - 1 ? (
            <Link to={crumb.to}>{crumb.label}</Link>
          ) : (
            <span>{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
