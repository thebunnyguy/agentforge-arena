import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiRequestError } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type {
  BackendKind,
  BackendVerifyResponse,
  JobParams,
} from "../api/types";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";

const STEPS = ["Backend", "Model", "Tasks", "Parameters", "Review"] as const;

export function NewEvaluation() {
  const navigate = useNavigate();
  const meta = useAsync((s) => api.meta(s), []);
  const settings = useAsync((s) => api.settings(s), []);

  const [step, setStep] = useState(0);

  // Backend
  const [kind, setKind] = useState<BackendKind>("mock");
  const [baseUrl, setBaseUrl] = useState("");
  const [verify, setVerify] = useState<BackendVerifyResponse | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);

  // Model / name
  const [model, setModel] = useState("mock");
  const [name, setName] = useState("mock");

  // Tasks
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Params
  const [repeats, setRepeats] = useState(1);
  const [baseSeed, setBaseSeed] = useState(42);
  const [temperature, setTemperature] = useState(0.8);
  const [timeout, setTimeout] = useState(180);

  const [launchErr, setLaunchErr] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  if (meta.loading) return <Loading />;
  if (meta.error) return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const tasks = meta.data!.tasks;

  // Apply settings defaults once loaded.
  function applyDefaults() {
    if (!settings.data) return;
    setRepeats(settings.data.default_repeats);
    setTemperature(settings.data.default_temperature);
    setTimeout(settings.data.default_request_timeout_s);
    if (kind === "ollama") setBaseUrl(settings.data.ollama_base_url);
    if (kind === "openai_compat" && settings.data.openai_base_url)
      setBaseUrl(settings.data.openai_base_url);
  }

  async function runVerify() {
    setVerifying(true);
    setVerifyErr(null);
    setVerify(null);
    try {
      const res = await api.verifyBackend({
        kind,
        base_url: kind === "mock" ? null : baseUrl || null,
      });
      setVerify(res);
      if (res.models.length > 0 && (model === "mock" || !model)) {
        setModel(res.models[0]);
        setName(res.models[0]);
      }
    } catch (e) {
      setVerifyErr(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setVerifying(false);
    }
  }

  const backendOk = kind === "mock" || (!!verify && verify.ok);

  function toggleTask(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const params: JobParams = {
    backend: { kind, base_url: kind === "mock" ? null : baseUrl || null },
    model,
    name,
    tasks: [...selected],
    repeats,
    base_seed: baseSeed,
    temperature,
    request_timeout_s: timeout,
  };

  const totalRuns = selected.size * repeats;

  async function launch() {
    setLaunching(true);
    setLaunchErr(null);
    try {
      const job = await api.createJob(params);
      navigate(`/jobs/${encodeURIComponent(job.id)}`);
    } catch (e) {
      setLaunchErr(e instanceof ApiRequestError ? e.message : String(e));
      setLaunching(false);
    }
  }

  const canNext =
    (step === 0 && backendOk) ||
    (step === 1 && model.trim().length > 0) ||
    (step === 2 && selected.size > 0) ||
    step === 3;

  return (
    <div>
      <h1 className="page-title">New evaluation</h1>
      <p className="page-subtitle">
        Configure and launch a local benchmark job. Local backends only.
      </p>
      <CaveatBanner caveat={meta.data?.notes?.trust} />

      <div className="wizard-steps">
        {STEPS.map((s, i) => (
          <div
            key={s}
            className={`wizard-step ${i === step ? "active" : ""} ${i < step ? "done" : ""}`}
          >
            <span className="n">{i + 1}</span>
            {s}
          </div>
        ))}
      </div>

      <div className="panel">
        {step === 0 && (
          <div>
            <h2>Backend &amp; verification</h2>
            <div className="field">
              <label>Backend kind</label>
              <select
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as BackendKind);
                  setVerify(null);
                  setVerifyErr(null);
                }}
              >
                <option value="mock">mock (deterministic, no model)</option>
                <option value="ollama">ollama (local)</option>
                <option value="openai_compat">openai-compatible (local server)</option>
              </select>
            </div>

            {kind !== "mock" && (
              <div className="field">
                <label>Base URL</label>
                <input
                  type="url"
                  value={baseUrl}
                  placeholder={
                    kind === "ollama"
                      ? "http://host.docker.internal:11434"
                      : "http://127.0.0.1:1234/v1"
                  }
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
                <div className="hint">
                  {kind === "openai_compat"
                    ? "Local OpenAI-compatible server (LM Studio / llama.cpp / vLLM). No API key is sent — auth is unsupported in v1."
                    : "Host Ollama. Verification hits /api/tags."}
                </div>
              </div>
            )}

            <div className="row-actions">
              <button className="btn secondary" onClick={runVerify} disabled={verifying}>
                {verifying ? "Verifying…" : kind === "mock" ? "Verify mock" : "Verify backend"}
              </button>
              {settings.data && (
                <button className="btn ghost" onClick={applyDefaults}>
                  Use settings defaults
                </button>
              )}
            </div>

            {verifyErr && (
              <p className="note" style={{ color: "var(--bad)" }}>
                {verifyErr}
              </p>
            )}
            {verify && (
              <div style={{ marginTop: 12 }}>
                <span className={`badge ${verify.ok ? "good" : "bad"}`}>
                  {verify.ok ? "reachable & ready" : "unreachable"}
                </span>{" "}
                <span className="note muted">{verify.detail}</span>
                {verify.models.length > 0 && (
                  <p className="note">Models: {verify.models.join(", ")}</p>
                )}
              </div>
            )}
            {kind === "mock" && (
              <p className="note muted">
                The mock backend produces deterministic runs with no model — ideal
                for verifying the pipeline end-to-end.
              </p>
            )}
          </div>
        )}

        {step === 1 && (
          <div>
            <h2>Model</h2>
            <div className="field">
              <label>Model id</label>
              {verify && verify.models.length > 0 ? (
                <select value={model} onChange={(e) => { setModel(e.target.value); setName(e.target.value); }}>
                  {verify.models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              ) : (
                <input type="text" value={model} onChange={(e) => setModel(e.target.value)} />
              )}
              <div className="hint">The local model id passed to the backend.</div>
            </div>
            <div className="field">
              <label>Display name (agent label)</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
              <div className="hint">How this run group appears in the leaderboard.</div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h2>Tasks ({selected.size} selected)</h2>
            <div className="row-actions" style={{ marginBottom: 10 }}>
              <button
                className="btn ghost"
                onClick={() => setSelected(new Set(tasks.map((t) => t.task_id)))}
              >
                Select all
              </button>
              <button className="btn ghost" onClick={() => setSelected(new Set())}>
                Clear
              </button>
            </div>
            <div className="task-grid">
              {tasks.map((t) => (
                <label key={t.task_id} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={selected.has(t.task_id)}
                    onChange={() => toggleTask(t.task_id)}
                  />
                  <span>{t.task_id}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div>
            <h2>Parameters</h2>
            <div className="grid-2">
              <div className="field">
                <label>Repeats per task</label>
                <input
                  type="number"
                  min={1}
                  value={repeats}
                  onChange={(e) => setRepeats(Math.max(1, Number(e.target.value)))}
                />
              </div>
              <div className="field">
                <label>Base seed</label>
                <input
                  type="number"
                  value={baseSeed}
                  onChange={(e) => setBaseSeed(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label>Temperature</label>
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
              </div>
              <div className="field">
                <label>Request timeout (s)</label>
                <input
                  type="number"
                  min={1}
                  value={timeout}
                  onChange={(e) => setTimeout(Math.max(1, Number(e.target.value)))}
                />
              </div>
            </div>
            <p className="note muted">
              {selected.size} tasks × {repeats} repeats = <strong>{totalRuns}</strong>{" "}
              runs.
            </p>
          </div>
        )}

        {step === 4 && (
          <div>
            <h2>Review &amp; launch</h2>
            <dl className="kv">
              <dt>backend</dt>
              <dd>{kind}{kind !== "mock" ? ` · ${baseUrl || "(default)"}` : ""}</dd>
              <dt>model</dt>
              <dd>{model}</dd>
              <dt>name</dt>
              <dd>{name}</dd>
              <dt>tasks</dt>
              <dd>{selected.size} selected</dd>
              <dt>repeats</dt>
              <dd>{repeats}</dd>
              <dt>base seed</dt>
              <dd>{baseSeed}</dd>
              <dt>temperature</dt>
              <dd>{temperature}</dd>
              <dt>request timeout</dt>
              <dd>{timeout}s</dd>
              <dt>total runs</dt>
              <dd>{totalRuns}</dd>
            </dl>
            {launchErr && (
              <p className="note" style={{ color: "var(--bad)" }}>
                {launchErr}
              </p>
            )}
            <p className="note muted">
              Launch creates a queued job; the worker picks it up and you'll be
              taken to the live monitor.
            </p>
          </div>
        )}

        <div className="wizard-actions">
          <button
            className="btn secondary"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            Back
          </button>
          {step < STEPS.length - 1 ? (
            <button className="btn" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          ) : (
            <button className="btn" disabled={launching || totalRuns === 0} onClick={launch}>
              {launching ? "Launching…" : `Launch (${totalRuns} runs)`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
