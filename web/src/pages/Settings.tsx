import { useEffect, useState } from "react";
import { api, ApiRequestError } from "../api/client";
import { useAsync } from "../lib/useAsync";
import type { AppSettings } from "../api/types";
import { CaveatBanner } from "../components/CaveatBanner";
import { ErrorState, Loading } from "../components/States";

export function Settings() {
  const loaded = useAsync((s) => api.settings(s), []);
  const [form, setForm] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (loaded.data) setForm(loaded.data);
  }, [loaded.data]);

  if (loaded.loading) return <Loading />;
  if (loaded.error) return <ErrorState error={loaded.error} onRetry={loaded.reload} />;
  if (!form) return <Loading />;

  function set<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
    setSaved(false);
  }

  async function save() {
    if (!form) return;
    setSaving(true);
    setErr(null);
    try {
      const next = await api.updateSettings(form);
      setForm(next);
      setSaved(true);
    } catch (e) {
      setErr(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">
        Persistent defaults for new evaluations and local backend URLs.
      </p>
      <CaveatBanner />

      <div className="panel">
        <h2>Backends</h2>
        <div className="field">
          <label>Ollama base URL</label>
          <input
            type="url"
            value={form.ollama_base_url}
            onChange={(e) => set("ollama_base_url", e.target.value)}
          />
        </div>
        <div className="field">
          <label>OpenAI-compatible base URL</label>
          <input
            type="url"
            value={form.openai_base_url ?? ""}
            onChange={(e) => set("openai_base_url", e.target.value || null)}
          />
          <div className="hint">
            Local server only. No API key field — the OpenAI-compatible agent does
            not send an Authorization header in v1.
          </div>
        </div>
        <div className="field">
          <label>Default backend</label>
          <select
            value={form.default_backend}
            onChange={(e) => set("default_backend", e.target.value as AppSettings["default_backend"])}
          >
            <option value="mock">mock</option>
            <option value="ollama">ollama</option>
            <option value="openai_compat">openai_compat</option>
          </select>
        </div>
      </div>

      <div className="panel">
        <h2>Evaluation defaults</h2>
        <div className="grid-2">
          <div className="field">
            <label>Default repeats</label>
            <input
              type="number"
              min={1}
              value={form.default_repeats}
              onChange={(e) => set("default_repeats", Math.max(1, Number(e.target.value)))}
            />
          </div>
          <div className="field">
            <label>Default temperature</label>
            <input
              type="number"
              step="0.1"
              min={0}
              value={form.default_temperature}
              onChange={(e) => set("default_temperature", Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Default request timeout (s)</label>
            <input
              type="number"
              min={1}
              value={form.default_request_timeout_s}
              onChange={(e) =>
                set("default_request_timeout_s", Math.max(1, Number(e.target.value)))
              }
            />
          </div>
        </div>

        <div className="row-actions" style={{ marginTop: 12 }}>
          <button className="btn" disabled={saving} onClick={save}>
            {saving ? "Saving…" : "Save settings"}
          </button>
          {saved && <span className="badge good">saved</span>}
          {err && (
            <span className="note" style={{ color: "var(--bad)" }}>
              {err}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
