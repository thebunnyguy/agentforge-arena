import type { CSSProperties } from "react";
import { pct } from "../lib/format";

interface Props {
  pHat: number;
  low: number;
  high: number;
  width?: number;
  showLabel?: boolean;
  compact?: boolean;
}

function plotX(value: number): number {
  return 2 + Math.max(0, Math.min(1, value)) * 96;
}

export function WilsonBar({
  pHat,
  low,
  high,
  width = 250,
  showLabel = true,
  compact = false,
}: Props) {
  const lowX = plotX(low);
  const highX = Math.max(lowX + 0.8, plotX(high));
  const pointX = plotX(pHat);
  const label = `Pass rate ${pct(pHat, 1)}. 95 percent Wilson interval from ${pct(low, 1)} to ${pct(high, 1)}.`;
  const css = { "--plot-max": `${width}px` } as CSSProperties;

  return (
    <div
      className={`confidence ${compact ? "confidence-compact" : ""}`}
      style={css}
    >
      <svg
        className="wilson-svg"
        viewBox="0 0 100 24"
        preserveAspectRatio="none"
        role="img"
        aria-label={label}
      >
        <title>{`p̂ ${pct(pHat, 1)} · 95% Wilson [${pct(low, 1)}, ${pct(high, 1)}]`}</title>
        <line className="plot-track" x1="2" y1="12" x2="98" y2="12" />
        <line className="plot-tick" x1="50" y1="5" x2="50" y2="19" />
        <line className="plot-tick" x1="98" y1="5" x2="98" y2="19" />
        <line className="plot-range" x1={lowX} y1="12" x2={highX} y2="12" />
        <line className="plot-cap" x1={lowX} y1="7" x2={lowX} y2="17" />
        <line className="plot-cap" x1={highX} y1="7" x2={highX} y2="17" />
        <circle className="plot-point" cx={pointX} cy="12" r="2.2" />
      </svg>
      <div className="plot-axis" aria-hidden="true">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
      {showLabel ? (
        <span className="wilson-label">
          <strong>{pct(pHat, 1)}</strong>
          <span>
            [{pct(low, 0)}–{pct(high, 0)}]
          </span>
        </span>
      ) : (
        <span className="wilson-label compact-range">
          [{pct(low, 0)}–{pct(high, 0)}]
        </span>
      )}
    </div>
  );
}
