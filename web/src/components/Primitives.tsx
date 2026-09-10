import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-subtitle">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SectionHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="section-action">{action}</div>}
    </div>
  );
}

export function Metric({
  label,
  value,
  detail,
  tone = "neutral",
  mono = false,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "accent" | "good" | "warn" | "bad" | "void";
  mono?: boolean;
}) {
  return (
    <div className={`metric metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${mono ? "mono" : ""}`}>{value}</div>
      {detail && <div className="metric-detail">{detail}</div>}
    </div>
  );
}

export function MetricGroup({ children }: { children: ReactNode }) {
  return <div className="metric-group">{children}</div>;
}

export function ProgressBar({
  value,
  label,
  tone = "accent",
}: {
  value: number;
  label?: string;
  tone?: "accent" | "good" | "warn" | "bad";
}) {
  const width = `${Math.max(0, Math.min(1, value)) * 100}%`;
  return (
    <div className="progress-wrap">
      <div
        className={`progress progress-${tone}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.max(0, Math.min(1, value)) * 100)}
        aria-label={label}
      >
        <div className="progress-fill" style={{ width }} />
      </div>
      {label && <span className="progress-label">{label}</span>}
    </div>
  );
}

export function StatusDot({
  label,
  tone = "neutral",
  pulse = false,
}: {
  label: string;
  tone?: "neutral" | "good" | "warn" | "bad" | "void" | "accent";
  pulse?: boolean;
}) {
  return (
    <span className="status-inline">
      <span
        className={`status-dot dot-${tone} ${pulse ? "dot-pulse" : ""}`}
        aria-hidden="true"
      />
      <span>{label}</span>
    </span>
  );
}

export function EvidenceStrip({
  items,
}: {
  items: Array<{
    label: string;
    value: ReactNode;
    tone?: "good" | "warn" | "bad" | "void" | "neutral";
  }>;
}) {
  return (
    <div className="evidence-strip">
      {items.map((item) => (
        <div className="evidence-item" key={item.label}>
          <span className="evidence-label">{item.label}</span>
          <span className={`evidence-value evidence-${item.tone ?? "neutral"}`}>
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Panel({
  children,
  className = "",
  tone,
}: {
  children: ReactNode;
  className?: string;
  tone?: "accent" | "good" | "warn" | "bad";
}) {
  return (
    <section className={`panel ${tone ? `panel-${tone}` : ""} ${className}`}>
      {children}
    </section>
  );
}

export function LinkArrow({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link className="link-arrow" to={to}>
      {children}
      <ArrowUpRight size={14} aria-hidden="true" />
    </Link>
  );
}

export function InlineNotice({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warn" | "danger" | "success";
}) {
  return (
    <div
      className={`inline-notice notice-${tone}`}
      role={tone === "danger" ? "alert" : undefined}
    >
      {children}
    </div>
  );
}

export function MonoValue({ children }: { children: ReactNode }) {
  return <span className="mono mono-value">{children}</span>;
}
