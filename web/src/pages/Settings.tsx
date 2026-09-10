import { useEffect, useState } from "react";
import { Check, CircleAlert, RefreshCw, Save, Server } from "lucide-react";
import { api, ApiRequestError } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type {
  AppSettings,
  BackendKind,
  BackendVerifyResponse,
} from "../api/types";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";
import {
  InlineNotice,
  PageHeader,
  Panel,
  SectionHeader,
} from "../components/Primitives";
import { backendLabel } from "../lib/format";

export function Settings() {
  const loaded = useAsync((signal) => api.settings(signal), []);
  const [form, setForm] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verify, setVerify] = useState<BackendVerifyResponse | null>(null);

  useEffect(() => {
    if (loaded.data) setForm(loaded.data);
  }, [loaded.data]);
  if (loaded.loading) return <Loading label="Loading settings…" />;
  if (loaded.error)
    return <ErrorState error={loaded.error} onRetry={loaded.reload} />;
  if (!form) return <Loading />;
  const currentForm = form;

  function set<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
    setVerify(null);
  }
  async function save() {
    setSaving(true);
    setErr(null);
    try {
      setForm(await api.updateSettings(currentForm));
      setSaved(true);
    } catch (caught) {
      setErr(
        caught instanceof ApiRequestError ? caught.message : String(caught),
      );
    } finally {
      setSaving(false);
    }
  }
  async function verifyBackend() {
    setVerifying(true);
    setVerify(null);
    const baseUrl =
      currentForm.default_backend === "ollama"
        ? currentForm.ollama_base_url
        : currentForm.default_backend === "openai_compat"
          ? currentForm.openai_base_url
          : null;
    try {
      setVerify(
        await api.verifyBackend({
          kind: currentForm.default_backend,
          base_url: baseUrl,
        }),
      );
    } catch (caught) {
      setVerify({
        kind: currentForm.default_backend,
        ok: false,
        detail: caught instanceof Error ? caught.message : String(caught),
        models: [],
      });
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Small, local defaults for the next evaluation. Changing these values does not rewrite past jobs or evidence."
      />
      <CaveatBanner />
      <Panel>
        <SectionHeader
          title="Local backends"
          description="Connection URLs are persisted as app defaults. Reachability is checked separately."
        />
        <div className="grid-2">
          <div className="field">
            <label htmlFor="ollama-url">Ollama base URL</label>
            <input
              id="ollama-url"
              type="url"
              value={form.ollama_base_url}
              onChange={(event) => set("ollama_base_url", event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="openai-url">OpenAI-compatible base URL</label>
            <input
              id="openai-url"
              type="url"
              value={form.openai_base_url ?? ""}
              onChange={(event) =>
                set("openai_base_url", event.target.value || null)
              }
            />
            <div className="hint">
              Local server only. The current OpenAI-compatible worker does not
              send an authorization header.
            </div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="default-backend">Default backend</label>
          <select
            id="default-backend"
            value={form.default_backend}
            onChange={(event) =>
              set("default_backend", event.target.value as BackendKind)
            }
          >
            <option value="mock">Mock</option>
            <option value="ollama">Ollama</option>
            <option value="openai_compat">OpenAI-compatible</option>
          </select>
        </div>
        <div className="row-actions">
          <button
            className="btn btn-secondary"
            type="button"
            disabled={verifying}
            onClick={verifyBackend}
          >
            <Server size={15} aria-hidden="true" />
            {verifying
              ? "Checking…"
              : `Verify ${backendLabel(form.default_backend)}`}
          </button>
          {verify && (
            <span className={`badge ${verify.ok ? "good" : "bad"}`}>
              {verify.ok
                ? `${verify.models.length} models available`
                : "unreachable"}
            </span>
          )}
        </div>
        {verify && (
          <InlineNotice tone={verify.ok ? "success" : "warn"}>
            {verify.ok ? (
              <Check size={16} aria-hidden="true" />
            ) : (
              <CircleAlert size={16} aria-hidden="true" />
            )}
            {verify.detail}
          </InlineNotice>
        )}
      </Panel>
      <Panel>
        <SectionHeader
          title="Evaluation defaults"
          description="Prefilled in New Evaluation; each launch stores its own parameters."
        />
        <div className="grid-3">
          <div className="field">
            <label htmlFor="default-repeats">Default repeats</label>
            <input
              id="default-repeats"
              type="number"
              min={1}
              value={form.default_repeats}
              onChange={(event) =>
                set("default_repeats", Math.max(1, Number(event.target.value)))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="default-temperature">Default temperature</label>
            <input
              id="default-temperature"
              type="number"
              min={0}
              step={0.1}
              value={form.default_temperature}
              onChange={(event) =>
                set("default_temperature", Number(event.target.value))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="default-timeout">Default request timeout</label>
            <input
              id="default-timeout"
              type="number"
              min={1}
              value={form.default_request_timeout_s}
              onChange={(event) =>
                set(
                  "default_request_timeout_s",
                  Math.max(1, Number(event.target.value)),
                )
              }
            />
            <div className="hint">
              seconds · saved setting; current worker does not forward it to
              every backend
            </div>
          </div>
        </div>
        <div className="row-actions">
          <button
            className="btn"
            type="button"
            disabled={saving}
            onClick={save}
          >
            <Save size={15} aria-hidden="true" />
            {saving ? "Saving…" : "Save defaults"}
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={loaded.reload}
          >
            <RefreshCw size={15} aria-hidden="true" /> Reload
          </button>
          {saved && <span className="badge good">saved</span>}
          {err && <span className="note bad-text">{err}</span>}
        </div>
      </Panel>
    </div>
  );
}
