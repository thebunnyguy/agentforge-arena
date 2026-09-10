import { BookOpen, Calculator, ShieldAlert } from "lucide-react";
import { api } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { CaveatBanner } from "../components/CaveatBanner";
import {
  InlineNotice,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";

export function Methodology() {
  const meta = useAsync((signal) => api.meta(signal), []);
  return (
    <div>
      <PageHeader
        eyebrow="Reference"
        title="Methodology"
        description="How AgentForge Arena turns trusted local run evidence into understandable benchmark results."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      <div className="split-layout">
        <div>
          <Panel>
            <SectionHeader title="One run" />
            <div className="formula">S = G · T_hidden · (0.85 + 0.15 · Q)</div>
            <dl className="method-list">
              <div>
                <dt>G</dt>
                <dd>
                  The product of the hard gates: setup, diff, scope, regression,
                  and timeout validity. One failed gate forces G = 0.
                </dd>
              </div>
              <div>
                <dt>T_hidden</dt>
                <dd>
                  The weighted fraction of hidden tests passed in the clean-room
                  grade. The agent does not see those tests.
                </dd>
              </div>
              <div>
                <dt>Q</dt>
                <dd>
                  A bounded quality modifier. Persisted v0.1 records may not
                  retain its component breakdown; unavailable Q components are
                  not treated as failures.
                </dd>
              </div>
              <div>
                <dt>S</dt>
                <dd>
                  The continuous final score used for diagnostics and
                  distribution evidence.
                </dd>
              </div>
              <div>
                <dt>X</dt>
                <dd>
                  Functional pass: all gates pass and all hidden tests pass. X
                  is the headline run outcome.
                </dd>
              </div>
            </dl>
          </Panel>
          <Panel>
            <SectionHeader title="Repeated runs and validity" />
            <p>
              Valid runs count toward n. TIMEOUT and AGENT_ERROR are valid
              failures. INFRA_FAILURE is voided because infrastructure failures
              are not evidence about an agent; voided attempts remain visible
              and are excluded from n.
            </p>
            <InlineNotice tone="info">
              <Calculator size={16} aria-hidden="true" />
              <span>
                The app displays server-owned aggregates; it does not turn score
                primitives into new statistics.
              </span>
            </InlineNotice>
          </Panel>
          <Panel>
            <SectionHeader title="Uncertainty and ranking" />
            <p>
              Each pass rate is paired with a 95% Wilson interval. The kernel
              ranks by the strict rule <code>LCB(a) &gt; p̂(b)</code>; otherwise
              agents share a rank range. This keeps overlapping evidence from
              becoming a false separation.
            </p>
            <p>
              Scopes with fewer than five valid runs are provisional and should
              not be read as stable leaderboard positions.
            </p>
          </Panel>
          <Panel>
            <SectionHeader title="Diagnostics, not promises" />
            <p>
              Stability describes consistency of the returned S values.
              Deterministic means repeated evidence hashes match; bimodal means
              pass and fail clusters make a mean especially misleading. pass@k
              is an in-sample retry diagnostic, not a guarantee about future
              independent attempts.
            </p>
          </Panel>
        </div>
        <div>
          <Panel>
            <SectionHeader title="Domains" />
            <p>
              Task metadata assigns weighted domain tags. A domain is
              displayable only when it covers at least <strong>5 tasks</strong>{" "}
              and <strong>25 runs</strong>. Suppressed domains show coverage but
              no performance value; suppression is not a zero.
            </p>
          </Panel>
          <Panel>
            <SectionHeader title="Versions and provenance" />
            <p>
              Every run retains a task version. The report path refuses to pool
              multiple versions inside a cell rather than blending incompatible
              task contracts. Run pages retain model/task identity, repeat
              index, task version, timestamps where available, and transcript
              hashes.
            </p>
          </Panel>
          <Panel>
            <SectionHeader title="Reference baselines and capture limits" />
            <dl className="method-list">
              <div>
                <dt>Oracle / noop</dt>
                <dd>
                  Synthetic reference bookends. They are not real competitors
                  and do not receive fabricated model provenance.
                </dd>
              </div>
              <div>
                <dt>Patch/tests</dt>
                <dd>
                  Legacy rows may lack patch or per-test artifacts. Missing
                  evidence is labelled missing, not rendered as an empty
                  success.
                </dd>
              </div>
              <div>
                <dt>Q components</dt>
                <dd>
                  Persisted v0.1 rows may expose Q but not its component list.
                </dd>
              </div>
              <div>
                <dt>Mixed pool</dt>
                <dd>
                  Mixed task versions are refused instead of silently averaged.
                </dd>
              </div>
            </dl>
          </Panel>
          <Panel>
            <SectionHeader title="Trusted-local boundary" />
            <InlineNotice tone="warn">
              <ShieldAlert size={16} aria-hidden="true" />
              <span>
                LocalSandbox runs agent code with host privileges. AgentForge
                Arena is a single-user local tool and makes no untrusted-agent
                isolation claim.
              </span>
            </InlineNotice>
          </Panel>
        </div>
      </div>
      <Panel>
        <SectionHeader title="Source of truth" />
        <p>
          <BookOpen size={15} aria-hidden="true" /> The frozen Python kernel
          owns scoring, aggregation, confidence intervals, domain pooling, and
          ranking. The local API projects those results to this workstation.
        </p>
      </Panel>
    </div>
  );
}
