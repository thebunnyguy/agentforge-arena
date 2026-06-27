import { pct, toPx } from "../lib/format";

// Renders a server-provided Wilson interval [low, high] with the point
// estimate p_hat. NO statistics are computed here — the three values arrive
// from the API; we only position them on a fixed-width pixel track (an
// explicitly-allowed display operation).
interface Props {
  pHat: number;
  low: number;
  high: number;
  width?: number;
  showLabel?: boolean;
}

export function WilsonBar({ pHat, low, high, width = 220, showLabel = true }: Props) {
  const lowPx = toPx(low, width);
  const highPx = toPx(high, width);
  const pHatPx = toPx(pHat, width);
  const intervalWidth = Math.max(2, highPx - lowPx);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div
        className="wilson"
        style={{ width }}
        title={`p̂ ${pct(pHat, 1)} · 95% Wilson [${pct(low, 1)}, ${pct(high, 1)}]`}
        role="img"
        aria-label={`pass rate ${pct(pHat, 1)}, Wilson interval ${pct(low, 1)} to ${pct(high, 1)}`}
      >
        <div className="phat" style={{ width: pHatPx }} />
        <div className="interval" style={{ left: lowPx, width: intervalWidth }} />
        <div className="point" style={{ left: pHatPx }} />
      </div>
      {showLabel && (
        <span className="wilson-label">
          {pct(pHat, 1)}{" "}
          <span style={{ color: "var(--text-faint)" }}>
            [{pct(low, 0)}–{pct(high, 0)}]
          </span>
        </span>
      )}
    </div>
  );
}
