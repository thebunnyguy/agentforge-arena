import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";

export function Methodology() {
  const meta = useAsync((s) => api.meta(s), []);
  return (
    <div>
      <h1 className="page-title">Methodology</h1>
      <p className="page-subtitle">
        How the frozen kernel scores runs, aggregates cells, and ranks agents.
        The app renders these values; it never recomputes them.
      </p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="panel">
        <h2>Per-run score S</h2>
        <p>
          Each run is scored deterministically by the kernel:
        </p>
        <pre className="log">{`S = G · T_hidden · (0.85 + 0.15·Q)`}</pre>
        <ul>
          <li>
            <strong>G</strong> — product of five binary hard gates (setup_ok,
            diff_exists, scope_ok, regression_pass, no_timeout). Any failed gate
            forces G=0, hence S=0.
          </li>
          <li>
            <strong>T_hidden</strong> — weighted fraction of hidden-suite tests
            that passed, in [0,1].
          </li>
          <li>
            <strong>Q</strong> — bounded quality modifier in [0,1] built from
            lint, typecheck, static analysis, security findings, and parsimony.
            Unavailable components are dropped and remaining weights renormalised;
            if <em>all</em> are unavailable, Q := 1.0 so absent evidence never
            penalises. The (0.85 + 0.15·Q) band caps Q's influence at ±15%.
          </li>
          <li>
            <strong>X</strong> (functional pass) — true iff G=1 and every hidden
            test passed.
          </li>
        </ul>
      </div>

      <div className="panel">
        <h2>Run status taxonomy & voided infra failures</h2>
        <ul>
          <li><strong>valid</strong> — executed and scorable; counts in n.</li>
          <li><strong>timeout</strong> — hit the wall-clock budget; counts in n as a failure (S=0).</li>
          <li><strong>agent_error</strong> — agent crashed / no usable result; counts in n as a failure (S=0).</li>
          <li>
            <strong>infra_failure</strong> — the platform's fault (sandbox,
            mirror, host). <em>Voided</em>: excluded from n, never scored against
            the agent.
          </li>
        </ul>
      </div>

      <div className="panel">
        <h2>Aggregation & Wilson intervals</h2>
        <p>
          Over the valid (non-voided) runs of a cell the kernel computes
          p̂ = n_pass / n_valid and a 95% Wilson score interval [low, high]. The
          interval — not p̂ alone — is the honest measure of certainty: small n
          yields a wide interval. The bars throughout this app draw the
          server-provided interval; the browser only positions the endpoints on a
          pixel track.
        </p>
        <p className="note muted">
          Other reported aggregates: mean/median/min/max S, Bessel-corrected std,
          stability = max(0, 1−2·std), a conservative continuous lower bound,
          reliability, timeout and infra-void rates, unbiased pass@k, and flags
          for deterministic / bimodal distributions.
        </p>
      </div>

      <div className="panel">
        <h2>Ranking & provisional status</h2>
        <p>
          Agents are ordered by their Wilson lower bound (LCB). Agent a strictly
          out-ranks b iff LCB_a &gt; p̂_b; otherwise they share a rank range.
          Agents with fewer than 5 valid runs in scope are <strong>provisional</strong>
          and excluded from ranking entirely.
        </p>
      </div>

      <div className="panel">
        <h2>Domain profiles & displayability</h2>
        <p>
          A domain pools the tasks tagged to it (weights 1.0 / 0.5 / 0.25 for
          primary / secondary / tertiary) into a pass rate with a Kish
          effective-n Wilson interval. A domain is only{" "}
          <strong>displayable</strong> with ≥5 tasks and ≥25 runs. Non-displayable
          domains render as <code>--</code> so sparse, imbalanced coverage is
          never dressed up as a confident number.
        </p>
      </div>

      <div className="panel">
        <h2>Captured vs not-captured vs synthetic</h2>
        <p>
          Recent runs capture the agent's patch, diff stats, and per-test results.
          Legacy rows predating capture show a clear <em>not captured</em> state
          rather than fabricating artifacts. If a synthetic baseline is ever
          included it is explicitly flagged <em>synthetic</em>.
        </p>
      </div>

      <div className="panel">
        <h2>Why trusted-local only</h2>
        <p>
          This is a single-user local tool. The clean room runs agent code with
          host privileges via LocalSandbox, which is <strong>not</strong> a
          security boundary. The app makes no untrusted-agent isolation claims and
          supports local model backends only — no paid or hosted LLM APIs.
        </p>
      </div>
    </div>
  );
}
