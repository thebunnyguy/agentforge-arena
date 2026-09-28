import { useEffect, useRef, useState, type ReactNode } from "react";
import { ExternalLink as ExternalIcon, Info } from "lucide-react";
import { Link } from "react-router-dom";
import { WilsonBar } from "../WilsonBar";
import { InlineNotice, PageHeader, Panel } from "../Primitives";
import { intervalText, statusTone } from "../../lib/benchmarkDisplay";
import type { ReleaseCaveat, ReleaseStatus } from "../../lib/benchmarkReleases";

/** Release status as a word badge (OFFICIAL, HISTORICAL, ...). */
export function ReleaseStatusBadge({ status }: { status: ReleaseStatus }) {
  return <span className={`badge ${statusTone(status)}`}>{status}</span>;
}

/** A served pass rate's Wilson 95% interval: compact plot plus the interval
 * as text, so the value never depends on reading the plot. */
export function WilsonInterval({
  pHat,
  low,
  high,
  width = 140,
}: {
  pHat: number;
  low: number;
  high: number;
  width?: number;
}) {
  return (
    <div className="bench-interval">
      <WilsonBar
        pHat={pHat}
        low={low}
        high={high}
        width={width}
        compact
        showLabel={false}
      />
      <span className="bench-interval-text mono">
        {intervalText(low, high)}
      </span>
    </div>
  );
}

/** Link to a file or ref outside the app (the frozen repository). */
export function ExternalLink({
  href,
  children,
}: {
  href: string | null;
  children: ReactNode;
}) {
  if (!href) return <>{children}</>;
  return (
    <a
      className="external-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <ExternalIcon size={12} aria-hidden="true" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

/** One caveat as a calm notice: label, summary, points and source. */
export function CaveatNotice({
  caveat,
  tone = "info",
  lead,
  after,
}: {
  caveat: ReleaseCaveat;
  tone?: "info" | "warn";
  lead?: ReactNode;
  after?: ReactNode;
}) {
  return (
    <InlineNotice tone={tone}>
      <Info size={16} aria-hidden="true" />
      <div className="notice-body" data-caveat={caveat.id}>
        <p>
          <strong>{lead ?? caveat.label}.</strong> {caveat.summary}
        </p>
        {caveat.points.length > 0 && (
          <ul className="notice-points">
            {caveat.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        )}
        {after}
        <p className="notice-source">
          Source: <span className="mono">{caveat.source}</span>
        </p>
      </div>
    </InlineNotice>
  );
}

/** Explicit not-found state for an unknown release or model id. */
export function BenchmarkNotFound({
  title,
  message,
  backTo,
  backLabel,
}: {
  title: string;
  message: ReactNode;
  backTo: string;
  backLabel: string;
}) {
  return (
    <div className="bench-page">
      <PageHeader eyebrow="Benchmark release" title={title} />
      <Panel>
        <p className="note">{message}</p>
        <Link className="btn btn-secondary" to={backTo}>
          {backLabel}
        </Link>
      </Panel>
    </div>
  );
}

/** A horizontally scrolling table wrapper: a named, focusable region (so
 * keyboard users can scroll it) with a visible "scroll for more" hint that
 * appears only while the table is wider than its container. The pinned first
 * column and the edge shadows are CSS (.bench-scroll). */
export function TableScroll({
  labelledBy,
  className = "",
  children,
}: {
  labelledBy: string;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const check = () =>
      setOverflows(element.scrollWidth > element.clientWidth + 1);
    check();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(check);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    return () => observer.disconnect();
  }, []);
  return (
    <>
      {overflows && (
        <p className="scroll-hint" data-scroll-hint="">
          Scroll sideways for more columns
          <span aria-hidden="true"> →</span>
        </p>
      )}
      <div
        ref={ref}
        className={`table-scroll bench-scroll ${className}`}
        tabIndex={overflows ? 0 : undefined}
        role="region"
        aria-labelledby={labelledBy}
      >
        {children}
      </div>
    </>
  );
}
