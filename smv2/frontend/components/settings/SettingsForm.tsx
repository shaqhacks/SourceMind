"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import {
  checkLlmStatus,
  clearProviderSecret,
  discoverOllamaModels,
  saveSettings,
  type LlmStatusOut,
  type OllamaModelsDiscoverIn,
  type SettingsOut,
} from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";

export interface SettingsFormProps {
  settings: SettingsOut;
  onSettings: (settings: SettingsOut) => void;
}

function editingEnabled(settings: SettingsOut): boolean {
  return settings.rollout.local_settings_enabled;
}

function readinessLabel(readiness: LlmStatusOut): string {
  if (readiness.available) return "Ready";
  if (!readiness.configured) return "Not configured";
  return "Unavailable";
}

type OllamaDiscoveryState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "loaded"; models: string[]; configuredModel: string | null; configuredModelAvailable: boolean }
  | { kind: "error"; category: string | null; message: string };

const DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434";

function missingConfiguredModelMessage(model: string): string {
  return `Your configured Ollama model “${model}” is not installed. Install it in Ollama or select another available model.`;
}

function ollamaErrorCategory(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const detail = "detail" in error ? (error as { detail?: unknown }).detail : error;
  if (!detail || typeof detail !== "object") return null;
  const category = "failure_category" in detail ? (detail as { failure_category?: unknown }).failure_category : null;
  return typeof category === "string" ? category : null;
}

function ollamaErrorMessage(category: string | null): string {
  if (category === "ollama_invalid_url") return "Ollama base URL must be an HTTP loopback origin.";
  if (category === "ollama_timeout") return "Ollama did not respond before the request timed out.";
  if (category === "ollama_unreachable") return "Ollama could not be reached.";
  if (category === "ollama_no_models" || category === "ollama_no_completion_models") {
    return "Ollama did not report any completion-capable models.";
  }
  return "Ollama returned an invalid discovery response.";
}

export default function SettingsForm({ settings, onSettings }: SettingsFormProps) {
  const canEdit = editingEnabled(settings);
  const [provider, setProvider] = useState<"anthropic" | "ollama">(
    settings.provider === "ollama" ? "ollama" : "anthropic",
  );
  const [model, setModel] = useState(settings.model);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("");
  const [ollamaDiscovery, setOllamaDiscovery] = useState<OllamaDiscoveryState>({ kind: "idle" });
  const [confirmation, setConfirmation] = useState("");
  const [status, setStatus] = useState<LlmStatusOut>(settings.readiness);
  const [message, setMessage] = useState<string | null>(null);
  const inFlightDiscovery = useRef<Promise<void> | null>(null);
  const discoveryRequestId = useRef(0);
  const didInitialOllamaDiscovery = useRef(false);
  const clearPhrase = `clear ${provider} credential`;
  const ollamaModels = ollamaDiscovery.kind === "loaded" ? ollamaDiscovery.models : [];
  const canSave =
    canEdit &&
    (provider === "anthropic" ||
      (ollamaDiscovery.kind === "loaded" && ollamaModels.includes(model)));

  const refreshOllamaModels = useCallback((body?: OllamaModelsDiscoverIn) => {
    if (inFlightDiscovery.current) return inFlightDiscovery.current;

    const requestId = discoveryRequestId.current + 1;
    discoveryRequestId.current = requestId;
    setOllamaDiscovery((current) => (current.kind === "loaded" ? current : { kind: "loading" }));

    const baseUrl = body && "base_url" in body ? body.base_url : (ollamaBaseUrl.trim() || null);
    const configuredModel = body && "configured_model" in body ? body.configured_model : (model || null);
    const discovery = discoverOllamaModels({
      base_url: baseUrl,
      configured_model: configuredModel,
    }).then((result) => {
      if (discoveryRequestId.current !== requestId) return;
      if (result.data) {
        const models = result.data.models;
        const configuredModel = result.data.configured_model;
        const configuredModelAvailable = result.data.configured_model_available;
        setOllamaDiscovery({ kind: "loaded", models, configuredModel, configuredModelAvailable });
        setModel((currentModel) => (models.includes(currentModel) ? currentModel : ""));
        return;
      }
      const category = ollamaErrorCategory(result.error);
      setOllamaDiscovery({ kind: "error", category, message: ollamaErrorMessage(category) });
      setModel("");
    }).finally(() => {
      if (inFlightDiscovery.current === discovery) inFlightDiscovery.current = null;
    });

    inFlightDiscovery.current = discovery;
    return discovery;
  }, [model, ollamaBaseUrl]);

  useEffect(() => {
    if (provider !== "ollama" || didInitialOllamaDiscovery.current) return;
    didInitialOllamaDiscovery.current = true;
    void refreshOllamaModels({ base_url: null, configured_model: settings.model || null });
  }, [provider, refreshOllamaModels, settings.model]);

  async function handleSave() {
    const credentials: Record<string, string> = {};
    if (anthropicKey) credentials.anthropic_api_key = anthropicKey;
    if (provider === "ollama" && ollamaBaseUrl) credentials.ollama_base_url = ollamaBaseUrl;
    const result = await saveSettings({ provider, model, credentials });
    if (result.data) {
      onSettings(result.data);
      setStatus(result.data.readiness);
      setMessage("Settings saved.");
      setAnthropicKey("");
      setOllamaBaseUrl("");
      setOllamaDiscovery(provider === "ollama" ? ollamaDiscovery : { kind: "idle" });
      return;
    }
    setMessage(describeError(result.status, "Saving settings").message);
  }

  async function handleCheck() {
    const result = await checkLlmStatus();
    if (result.data) {
      setStatus(result.data);
      setMessage(result.data.available ? "Connection available." : "Connection unavailable.");
      return;
    }
    setMessage(describeError(result.status, "Testing connection").message);
  }

  async function handleClear() {
    if (confirmation !== clearPhrase) return;
    const result = await clearProviderSecret(provider, confirmation);
    if (result.data) {
      onSettings(result.data);
      setMessage(`${provider} credential cleared.`);
      setConfirmation("");
      return;
    }
    setMessage(describeError(result.status, "Clearing credential").message);
  }

  function handleProviderChange(nextProvider: "anthropic" | "ollama") {
    setProvider(nextProvider);
    setMessage(null);
    if (nextProvider === "ollama") {
      const baseUrl = ollamaBaseUrl || DEFAULT_OLLAMA_BASE_URL;
      didInitialOllamaDiscovery.current = true;
      setModel("");
      setOllamaBaseUrl(baseUrl);
      void refreshOllamaModels({ base_url: baseUrl, configured_model: null });
      return;
    }
    discoveryRequestId.current += 1;
    inFlightDiscovery.current = null;
    setOllamaDiscovery({ kind: "idle" });
    setModel(settings.provider === "anthropic" ? settings.model : "");
  }

  function handleOllamaBaseUrlChange(value: string) {
    discoveryRequestId.current += 1;
    inFlightDiscovery.current = null;
    setOllamaBaseUrl(value);
    setModel("");
    setOllamaDiscovery({ kind: "idle" });
  }

  const showMissingConfiguredModel =
    provider === "ollama" &&
    ollamaDiscovery.kind === "loaded" &&
    !ollamaDiscovery.configuredModelAvailable &&
    Boolean(ollamaDiscovery.configuredModel) &&
    !model;

  return (
    <div className="flex flex-col gap-5">
      <section className="rounded-md border border-divider bg-surface-raised p-4">
        <h2 className="font-heading text-xl">AI Provider</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Provider
            <select
              value={provider}
              onChange={(event) => handleProviderChange(event.target.value as "anthropic" | "ollama")}
              disabled={!canEdit}
              className="rounded-md border border-border bg-background p-2"
            >
              <option value="anthropic">anthropic</option>
              <option value="ollama">ollama</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            Model
            {provider === "ollama" ? (
              <select
                value={model}
                onChange={(event) => setModel(event.target.value)}
                onPointerDown={() => void refreshOllamaModels({ configured_model: model || null })}
                disabled={!canEdit}
                className="rounded-md border border-border bg-background p-2"
              >
                <option value="">Select an installed model</option>
                {ollamaModels.map((ollamaModel) => (
                  <option key={ollamaModel} value={ollamaModel}>{ollamaModel}</option>
                ))}
              </select>
            ) : (
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                disabled={!canEdit}
                className="rounded-md border border-border bg-background p-2"
              />
            )}
          </label>
        </div>
        <p className="mt-3 text-sm">
          Readiness: <strong>{readinessLabel(status)}</strong>
        </p>
        {status.remediation && <p className="mt-1 text-sm text-muted-foreground">{status.remediation}</p>}
        {provider === "ollama" && ollamaDiscovery.kind === "loading" && (
          <p className="mt-1 text-sm text-muted-foreground">Loading installed Ollama models...</p>
        )}
        {provider === "ollama" && ollamaDiscovery.kind === "loaded" && ollamaModels.length === 0 && (
          <p className="mt-1 text-sm text-muted-foreground">{ollamaErrorMessage("ollama_no_completion_models")}</p>
        )}
        {showMissingConfiguredModel && (
          <p className="mt-1 text-sm text-muted-foreground">
            {missingConfiguredModelMessage(ollamaDiscovery.configuredModel ?? "")}
          </p>
        )}
        {provider === "ollama" && ollamaDiscovery.kind === "error" && (
          <p className="mt-1 text-sm text-muted-foreground">{ollamaDiscovery.message}</p>
        )}
      </section>

      <section className="rounded-md border border-divider bg-surface-raised p-4">
        <h2 className="font-heading text-xl">Credentials</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {settings.credentials_present.anthropic ? "anthropic credential saved" : "anthropic credential missing"}
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Anthropic API key
            <input
              type="password"
              value={anthropicKey}
              onChange={(event) => setAnthropicKey(event.target.value)}
              disabled={!canEdit}
              autoComplete="off"
              className="rounded-md border border-border bg-background p-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            Ollama base URL
            <input
              value={ollamaBaseUrl}
              onChange={(event) => handleOllamaBaseUrlChange(event.target.value)}
              disabled={!canEdit}
              className="rounded-md border border-border bg-background p-2"
            />
          </label>
        </div>
        <label className="mt-4 flex flex-col gap-1 text-sm font-medium">
          Confirmation
          <input
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            disabled={!canEdit}
            placeholder={clearPhrase}
            className="rounded-md border border-border bg-background p-2"
          />
        </label>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => void handleSave()} disabled={!canSave}>
            Save settings
          </Button>
          <Button onClick={() => void handleCheck()}>Test connection</Button>
          <Button
            variant="danger"
            onClick={() => void handleClear()}
            disabled={!canEdit || confirmation !== clearPhrase}
          >
            Clear {provider} credential
          </Button>
        </div>
        {message && <p className="mt-3 text-sm text-muted-foreground">{message}</p>}
      </section>
    </div>
  );
}
