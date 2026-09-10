import { useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Cpu,
  Database,
  FlaskConical,
  Rocket,
  Search,
  Server,
} from "lucide-react";
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
import {
  InlineNotice,
  Metric,
  MetricGroup,
  PageHeader,
  Panel,
} from "../components/Primitives";
import { backendLabel, taskScope } from "../lib/format";
import {
  hasVerifiedModel,
  validEvaluationParams,
  verificationKey,
} from "../lib/evaluationValidation";

const STEPS = ["Backend", "Model", "Tasks", "Parameters", "Review"] as const;
const BACKENDS: Array<{
  kind: BackendKind;
  title: string;
  detail: string;
  icon: typeof Server;
}> = [
  {
    kind: "ollama",
    title: "Ollama",
    detail: "Local Ollama server · recommended",
    icon: Server,
  },
  {
    kind: "openai_compat",
    title: "OpenAI-compatible",
    detail: "LM Studio · llama.cpp · vLLM",
    icon: Cpu,
  },
  {
    kind: "mock",
    title: "Mock",
    detail: "Deterministic offline test mode",
    icon: FlaskConical,
  },
];

type TaskOption = {
  task_id: string;
  activity?: string | null;
  difficulty?: number | string | null;
  domains: Array<{ domain: string; weight: number }>;
};

export function NewEvaluation() {
  const navigate = useNavigate();
  const meta = useAsync((signal) => api.meta(signal), []);
  const settings = useAsync((signal) => api.settings(signal), []);
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState<BackendKind>("mock");
  const [baseUrl, setBaseUrl] = useState("");
  const [verify, setVerify] = useState<BackendVerifyResponse | null>(null);
  const [verifiedKey, setVerifiedKey] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [taskQuery, setTaskQuery] = useState("");
  const [taskDomain, setTaskDomain] = useState("");
  const [repeats, setRepeats] = useState<number | "">(1);
  const [baseSeed, setBaseSeed] = useState<number | "">(42);
  const [temperature, setTemperature] = useState<number | "">(0.8);
  const [timeout, setTimeoutValue] = useState<number | "">(180);
  const [launchErr, setLaunchErr] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const defaultsApplied = useRef(false);
  const userTouched = useRef(false);
  const verifyAbort = useRef<AbortController | null>(null);
  const verificationGeneration = useRef(0);
  const requestKeyRef = useRef("");
  const stepFocusRef = useRef<HTMLDivElement>(null);
  const requestKey = verificationKey(kind, baseUrl);
  requestKeyRef.current = requestKey;

  function invalidateVerification(nextKey: string) {
    verificationGeneration.current += 1;
    requestKeyRef.current = nextKey;
    verifyAbort.current?.abort();
    verifyAbort.current = null;
    setVerifying(false);
    setVerify(null);
    setVerifiedKey(null);
    setVerifyErr(null);
    setModel("");
    setName("");
  }

  useEffect(() => {
    if (!settings.data || defaultsApplied.current || userTouched.current)
      return;
    defaultsApplied.current = true;
    setKind(settings.data.default_backend);
    setRepeats(settings.data.default_repeats);
    setTemperature(settings.data.default_temperature);
    setTimeoutValue(settings.data.default_request_timeout_s);
    if (settings.data.default_backend === "ollama")
      setBaseUrl(settings.data.ollama_base_url);
    if (settings.data.default_backend === "openai_compat")
      setBaseUrl(settings.data.openai_base_url ?? "");
  }, [settings.data]);

  useEffect(() => {
    invalidateVerification(requestKey);
  }, [requestKey]);

  useEffect(() => {
    return () => {
      verificationGeneration.current += 1;
      verifyAbort.current?.abort();
    };
  }, []);

  useEffect(() => {
    stepFocusRef.current?.focus();
  }, [step]);

  const tasks = meta.data?.tasks ?? [];
  const domains = [
    ...new Set(tasks.flatMap((task) => task.domains.map((tag) => tag.domain))),
  ].sort();
  const needle = taskQuery.trim().toLowerCase();
  const visibleTasks = tasks.filter(
    (task) =>
      (!needle ||
        task.task_id.toLowerCase().includes(needle) ||
        (task.activity ?? "").toLowerCase().includes(needle)) &&
      (!taskDomain || task.domains.some((tag) => tag.domain === taskDomain)),
  );
  if (meta.loading) return <Loading label="Loading evaluation setup…" />;
  if (meta.error)
    return <ErrorState error={meta.error} onRetry={meta.reload} />;

  const verifiedModels =
    verify?.ok && verifiedKey === requestKey ? verify.models : [];
  const backendOk = verify?.ok === true && verifiedKey === requestKey;
  const numericRepeats = typeof repeats === "number" ? repeats : 0;
  const numericSeed = typeof baseSeed === "number" ? baseSeed : 0;
  const numericTemperature = typeof temperature === "number" ? temperature : 0;
  const numericTimeout = typeof timeout === "number" ? timeout : 0;
  const params: JobParams = {
    backend: { kind, base_url: kind === "mock" ? null : baseUrl || null },
    model,
    name: name || model,
    tasks: [...selected],
    repeats: numericRepeats,
    base_seed: numericSeed,
    temperature: numericTemperature,
    request_timeout_s: numericTimeout,
  };
  const totalRuns =
    typeof repeats === "number" && Number.isInteger(repeats) && repeats >= 1
      ? selected.size * repeats
      : 0;
  const paramsValid = validEvaluationParams({
    repeats,
    baseSeed,
    temperature,
    timeout,
  });
  const modelVerified = hasVerifiedModel(
    verify,
    verifiedKey,
    requestKey,
    model,
  );
  const canNext =
    step === 0
      ? backendOk && !settings.loading
      : step === 1
        ? modelVerified
        : step === 2
          ? selected.size > 0
          : step === 3
            ? paramsValid
            : true;

  function touch() {
    userTouched.current = true;
  }
  function changeKind(next: BackendKind) {
    touch();
    const nextBaseUrl =
      next === "ollama"
        ? (settings.data?.ollama_base_url ?? "")
        : next === "openai_compat"
          ? (settings.data?.openai_base_url ?? "")
          : "";
    invalidateVerification(verificationKey(next, nextBaseUrl));
    setKind(next);
    setBaseUrl(nextBaseUrl);
  }
  function changeBaseUrl(next: string) {
    touch();
    invalidateVerification(verificationKey(kind, next));
    setBaseUrl(next);
  }
  function changeModel(next: string) {
    touch();
    setModel(next);
    setName(next);
  }
  function changeName(next: string) {
    touch();
    setName(next);
  }

  async function verifyBackend() {
    const keyAtStart = requestKeyRef.current;
    const generationAtStart = verificationGeneration.current + 1;
    verificationGeneration.current = generationAtStart;
    verifyAbort.current?.abort();
    const controller = new AbortController();
    verifyAbort.current = controller;
    const isCurrent = () =>
      !controller.signal.aborted &&
      verificationGeneration.current === generationAtStart &&
      requestKeyRef.current === keyAtStart;
    setVerifying(true);
    setVerifyErr(null);
    setVerify(null);
    setVerifiedKey(null);
    try {
      const result = await api.verifyBackend(
        { kind, base_url: kind === "mock" ? null : baseUrl || null },
        controller.signal,
      );
      if (!isCurrent()) return;
      setVerify(result);
      setVerifiedKey(result.ok ? keyAtStart : null);
      if (result.models.length > 0) {
        setModel(result.models[0]);
        setName(result.models[0]);
      }
    } catch (error) {
      if (!isCurrent()) return;
      setVerifyErr(
        error instanceof ApiRequestError ? error.message : String(error),
      );
    } finally {
      if (isCurrent()) {
        setVerifying(false);
        verifyAbort.current = null;
      }
    }
  }

  function toggleTask(taskId: string) {
    touch();
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }
  function selectVisible() {
    touch();
    setSelected(
      (current) =>
        new Set([...current, ...visibleTasks.map((task) => task.task_id)]),
    );
  }
  function clearVisible() {
    touch();
    setSelected(
      (current) =>
        new Set(
          [...current].filter(
            (id) => !visibleTasks.some((task) => task.task_id === id),
          ),
        ),
    );
  }
  function selectAll() {
    touch();
    setSelected(new Set(tasks.map((task) => task.task_id)));
  }
  function clearAll() {
    touch();
    setSelected(new Set());
  }

  async function launch() {
    if (!modelVerified || !paramsValid || totalRuns === 0) {
      setLaunchErr(
        "Verify a model, select at least one task, and enter valid integer run parameters before launching.",
      );
      return;
    }
    setLaunching(true);
    setLaunchErr(null);
    try {
      const job = await api.createJob(params);
      navigate(`/jobs/${encodeURIComponent(job.id)}`);
    } catch (error) {
      setLaunchErr(
        error instanceof ApiRequestError ? error.message : String(error),
      );
      setLaunching(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Evaluate"
        title="New evaluation"
        description="Set up a controlled local experiment. Verification, scope, and run size stay visible before launch."
      />
      <CaveatBanner caveat={meta.data?.notes?.trust} />
      {settings.loading && (
        <InlineNotice tone="info">
          Saved defaults are loading. Backend verification will be available
          when the settings read finishes.
        </InlineNotice>
      )}
      {settings.error && (
        <InlineNotice tone="warn">
          <CircleAlert size={16} aria-hidden="true" />
          <span>
            Saved defaults could not be loaded. You can continue with explicit
            values and retry from Settings.
          </span>
        </InlineNotice>
      )}
      <div className="wizard-shell">
        <nav className="wizard-steps" aria-label="Evaluation setup steps">
          {STEPS.map((label, index) => (
            <button
              type="button"
              key={label}
              className={`wizard-step ${index === step ? "active" : ""} ${index < step ? "done" : ""}`}
              disabled={index > step}
              aria-current={index === step ? "step" : undefined}
              onClick={() => index <= step && setStep(index)}
            >
              <span className="n">
                {index < step ? (
                  <Check size={12} aria-hidden="true" />
                ) : (
                  index + 1
                )}
              </span>
              {label}
            </button>
          ))}
        </nav>
        <Panel className="wizard-panel">
          <div ref={stepFocusRef} className="wizard-content" tabIndex={-1}>
            {step === 0 && (
              <BackendStep
                kind={kind}
                baseUrl={baseUrl}
                verify={verify}
                verifying={verifying}
                verifyErr={verifyErr}
                onKindChange={changeKind}
                onBaseUrlChange={changeBaseUrl}
                onVerify={verifyBackend}
                settingsLoading={settings.loading}
              />
            )}
            {step === 1 && (
              <ModelStep
                kind={kind}
                model={model}
                name={name}
                models={verifiedModels}
                onModelChange={changeModel}
                onNameChange={changeName}
              />
            )}
            {step === 2 && (
              <TaskStep
                tasks={tasks}
                visibleTasks={visibleTasks}
                domains={domains}
                selected={selected}
                query={taskQuery}
                domain={taskDomain}
                onQuery={setTaskQuery}
                onDomain={setTaskDomain}
                onToggle={toggleTask}
                onSelectVisible={selectVisible}
                onClearVisible={clearVisible}
                onSelectAll={selectAll}
                onClearAll={clearAll}
              />
            )}
            {step === 3 && (
              <ParameterStep
                repeats={repeats}
                seed={baseSeed}
                temperature={temperature}
                timeout={timeout}
                totalRuns={totalRuns}
                selectedCount={selected.size}
                onRepeats={setRepeats}
                onSeed={setBaseSeed}
                onTemperature={setTemperature}
                onTimeout={setTimeoutValue}
              />
            )}
            {step === 4 && (
              <ReviewStep
                params={params}
                totalRuns={totalRuns}
                launchErr={launchErr}
              />
            )}
          </div>
          <div className="wizard-actions">
            <button
              className="btn btn-secondary"
              type="button"
              disabled={step === 0}
              onClick={() => setStep((current) => Math.max(0, current - 1))}
            >
              <ChevronLeft size={15} aria-hidden="true" /> Back
            </button>
            {step < STEPS.length - 1 ? (
              <button
                className="btn"
                type="button"
                disabled={!canNext}
                onClick={() => setStep((current) => current + 1)}
              >
                Continue <ChevronRight size={15} aria-hidden="true" />
              </button>
            ) : (
              <button
                className="btn"
                type="button"
                disabled={
                  launching || totalRuns === 0 || !modelVerified || !paramsValid
                }
                onClick={launch}
              >
                {launching ? (
                  "Launching…"
                ) : (
                  <>
                    <Rocket size={15} aria-hidden="true" /> Launch {totalRuns}{" "}
                    runs
                  </>
                )}
              </button>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function BackendStep({
  kind,
  baseUrl,
  verify,
  verifying,
  verifyErr,
  onKindChange,
  onBaseUrlChange,
  onVerify,
  settingsLoading,
}: {
  kind: BackendKind;
  baseUrl: string;
  verify: BackendVerifyResponse | null;
  verifying: boolean;
  verifyErr: string | null;
  onKindChange: (kind: BackendKind) => void;
  onBaseUrlChange: (value: string) => void;
  onVerify: () => void;
  settingsLoading: boolean;
}) {
  return (
    <div>
      <h2>Where is your model running?</h2>
      <p className="note muted">
        Pick a local backend, then verify its reachable model list before
        continuing. Mock also requires explicit verification so every launch has
        the same readiness contract.
      </p>
      <div className="option-grid">
        {BACKENDS.map((backend) => {
          const Icon = backend.icon;
          return (
            <button
              type="button"
              className={`option-card ${kind === backend.kind ? "selected" : ""}`}
              key={backend.kind}
              aria-pressed={kind === backend.kind}
              disabled={settingsLoading}
              onClick={() => onKindChange(backend.kind)}
            >
              <Icon className="option-icon" size={20} aria-hidden="true" />
              <strong>{backend.title}</strong>
              <small>{backend.detail}</small>
              {kind === backend.kind && (
                <span className="selected-mark">
                  <Check size={15} aria-label="Selected" />
                </span>
              )}
            </button>
          );
        })}
      </div>
      {kind !== "mock" && (
        <div className="field wizard-offset">
          <label htmlFor="backend-url">Base URL</label>
          <input
            id="backend-url"
            type="url"
            value={baseUrl}
            placeholder={
              kind === "ollama"
                ? "http://localhost:11434"
                : "http://127.0.0.1:1234"
            }
            disabled={settingsLoading}
            onChange={(event) => onBaseUrlChange(event.target.value)}
          />
          <div className="hint">
            {kind === "ollama"
              ? "Verification reads /api/tags."
              : "Verification reads /v1/models. The current worker dispatch still uses the Ollama generation path for this backend, does not forward an authorization header, and does not enforce request_timeout_s."}
          </div>
        </div>
      )}
      <div className="row-actions wizard-actions-row">
        <button
          className="btn btn-secondary"
          type="button"
          disabled={verifying || settingsLoading}
          onClick={onVerify}
        >
          {verifying ? "Checking…" : "Verify backend"}
        </button>
        {verify && (
          <span className={`badge ${verify.ok ? "good" : "bad"}`}>
            {verify.ok
              ? `${verify.models.length} model${verify.models.length === 1 ? "" : "s"} available`
              : "Could not connect"}
          </span>
        )}
      </div>
      {verifyErr && (
        <InlineNotice tone="danger">
          <CircleAlert size={16} aria-hidden="true" />
          {verifyErr}
        </InlineNotice>
      )}
      {verify && (
        <InlineNotice tone={verify.ok ? "success" : "warn"}>
          <Database size={16} aria-hidden="true" />
          {verify.detail}
        </InlineNotice>
      )}
    </div>
  );
}

function ModelStep({
  kind,
  model,
  name,
  models,
  onModelChange,
  onNameChange,
}: {
  kind: BackendKind;
  model: string;
  name: string;
  models: string[];
  onModelChange: (value: string) => void;
  onNameChange: (value: string) => void;
}) {
  return (
    <div>
      <h2>Choose a model</h2>
      <p className="note muted">
        Choose from model IDs returned by the current successful backend check.
      </p>
      {models.length > 0 ? (
        <div className="model-list">
          {models.map((item) => (
            <button
              type="button"
              className={`model-option ${model === item ? "selected" : ""}`}
              key={item}
              aria-pressed={model === item}
              onClick={() => onModelChange(item)}
            >
              <span>
                <Cpu size={16} aria-hidden="true" />
                <strong>{item}</strong>
                <small>{backendLabel(kind)} · verified model ID</small>
              </span>
              {model === item && <Check size={16} aria-label="Selected" />}
            </button>
          ))}
        </div>
      ) : (
        <InlineNotice tone="warn">
          Verify this backend on the previous step to discover available model
          IDs.
        </InlineNotice>
      )}
      <div className="field wizard-offset">
        <label htmlFor="agent-name">Display label</label>
        <input
          id="agent-name"
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
        />
        <div className="hint">
          The worker stamps persisted runs with the model ID. This label is
          retained in the job configuration and should normally match it.
        </div>
      </div>
    </div>
  );
}

function TaskStep({
  tasks,
  visibleTasks,
  domains,
  selected,
  query,
  domain,
  onQuery,
  onDomain,
  onToggle,
  onSelectVisible,
  onClearVisible,
  onSelectAll,
  onClearAll,
}: {
  tasks: Array<{ task_id: string }>;
  visibleTasks: TaskOption[];
  domains: string[];
  selected: Set<string>;
  query: string;
  domain: string;
  onQuery: (value: string) => void;
  onDomain: (value: string) => void;
  onToggle: (id: string) => void;
  onSelectVisible: () => void;
  onClearVisible: () => void;
  onSelectAll: () => void;
  onClearAll: () => void;
}) {
  return (
    <div>
      <h2>Choose benchmark tasks</h2>
      <p className="note muted">
        Select a full pack or a focused subset. Task-owned grading parameters
        remain in the task contract.
      </p>
      <div className="task-selector">
        <div className="task-selector-toolbar">
          <div className="search-field field-search">
            <Search size={15} aria-hidden="true" />
            <input
              aria-label="Search benchmark tasks"
              value={query}
              onChange={(event) => onQuery(event.target.value)}
              placeholder="Filter task IDs…"
            />
          </div>
          <select
            aria-label="Filter tasks by domain"
            value={domain}
            onChange={(event) => onDomain(event.target.value)}
          >
            <option value="">All domains</option>
            {domains.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <button
            className="btn btn-ghost btn-small"
            type="button"
            onClick={onSelectAll}
          >
            Select all
          </button>
          <button
            className="btn btn-ghost btn-small"
            type="button"
            onClick={onClearAll}
          >
            Clear all
          </button>
          <button
            className="btn btn-ghost btn-small"
            type="button"
            onClick={onSelectVisible}
          >
            Select visible
          </button>
          <button
            className="btn btn-ghost btn-small"
            type="button"
            onClick={onClearVisible}
          >
            Clear visible
          </button>
        </div>
        <div className="evidence-strip">
          <div className="evidence-item">
            <span className="evidence-label">Selected</span>
            <span className="evidence-value evidence-good">
              {selected.size} / {tasks.length}
            </span>
          </div>
          <div className="evidence-item">
            <span className="evidence-label">Showing</span>
            <span className="evidence-value">{visibleTasks.length}</span>
          </div>
        </div>
        <div className="task-grid">
          {visibleTasks.map((task) => (
            <label
              className={`task-option ${selected.has(task.task_id) ? "selected" : ""}`}
              key={task.task_id}
            >
              <input
                type="checkbox"
                checked={selected.has(task.task_id)}
                onChange={() => onToggle(task.task_id)}
              />
              <span className="task-option-body">
                <span className="task-option-title">{task.task_id}</span>
                <span className="task-option-meta">
                  <span className="task-tag">
                    {task.activity ?? "benchmark task"}
                  </span>
                  <span className="task-tag">
                    difficulty {task.difficulty ?? "—"}
                  </span>
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

function parseField(value: string): number | "" {
  if (value === "") return "";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : "";
}

function ParameterStep({
  repeats,
  seed,
  temperature,
  timeout,
  totalRuns,
  selectedCount,
  onRepeats,
  onSeed,
  onTemperature,
  onTimeout,
}: {
  repeats: number | "";
  seed: number | "";
  temperature: number | "";
  timeout: number | "";
  totalRuns: number;
  selectedCount: number;
  onRepeats: (value: number | "") => void;
  onSeed: (value: number | "") => void;
  onTemperature: (value: number | "") => void;
  onTimeout: (value: number | "") => void;
}) {
  return (
    <div>
      <h2>Experiment parameters</h2>
      <p className="note muted">
        These are runner controls. Request timeout is a saved request setting;
        the current worker does not enforce it for every backend.
      </p>
      <MetricGroup>
        <Metric
          label="Planned evaluation"
          value={
            typeof repeats === "number"
              ? taskScope(selectedCount, repeats)
              : "—"
          }
          detail="tasks × repeats"
          tone="accent"
        />
        <Metric
          label="Total runs"
          value={totalRuns}
          detail="before any reuse or voids"
          tone="good"
          mono
        />
      </MetricGroup>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="repeats">Repeats per task</label>
          <input
            id="repeats"
            type="number"
            min={1}
            step={1}
            value={repeats}
            onChange={(event) => onRepeats(parseField(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="seed">Base seed</label>
          <input
            id="seed"
            type="number"
            step={1}
            value={seed}
            onChange={(event) => onSeed(parseField(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="temperature">Temperature</label>
          <input
            id="temperature"
            type="number"
            min={0}
            step={0.1}
            value={temperature}
            onChange={(event) => onTemperature(parseField(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="request-timeout">Request timeout (seconds)</label>
          <input
            id="request-timeout"
            type="number"
            min={1}
            step={1}
            value={timeout}
            onChange={(event) => onTimeout(parseField(event.target.value))}
          />
        </div>
      </div>
    </div>
  );
}

function ReviewStep({
  params,
  totalRuns,
  launchErr,
}: {
  params: JobParams;
  totalRuns: number;
  launchErr: string | null;
}) {
  return (
    <div>
      <h2>Review evaluation plan</h2>
      <p className="note muted">
        Launching creates a durable evaluation record. The monitor will show
        fresh, reused, failed, and voided units separately.
      </p>
      <div className="review-grid">
        <div className="review-item">
          <span className="review-label">Backend</span>
          <span className="review-value">
            {backendLabel(params.backend.kind)}
          </span>
        </div>
        <div className="review-item">
          <span className="review-label">Model</span>
          <span className="review-value">{params.model}</span>
        </div>
        <div className="review-item">
          <span className="review-label">Tasks</span>
          <span className="review-value">{params.tasks.length}</span>
        </div>
        <div className="review-item">
          <span className="review-label">Repeats</span>
          <span className="review-value">{params.repeats}</span>
        </div>
        <div className="review-item">
          <span className="review-label">Total</span>
          <span className="review-value">{totalRuns} runs</span>
        </div>
        <div className="review-item">
          <span className="review-label">Base seed</span>
          <span className="review-value">{params.base_seed}</span>
        </div>
        <div className="review-item">
          <span className="review-label">Temperature</span>
          <span className="review-value">{params.temperature}</span>
        </div>
        <div className="review-item">
          <span className="review-label">Request timeout</span>
          <span className="review-value">{params.request_timeout_s}s</span>
        </div>
      </div>
      {launchErr && (
        <InlineNotice tone="danger">
          <CircleAlert size={16} aria-hidden="true" />
          {launchErr}
        </InlineNotice>
      )}
      <InlineNotice tone="info">
        <Rocket size={16} aria-hidden="true" />
        <span>
          After launch, cancellation is honored between runs. A running model
          request may finish before the job stops.
        </span>
      </InlineNotice>
    </div>
  );
}
