"use client";

import { useState } from "react";

import Button from "@/components/ui/Button";
import {
  checkLlmStatus,
  clearProviderSecret,
  saveSettings,
  type LlmStatusOut,
  type SettingsOut,
} from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";

export interface SettingsFormProps {
  settings: SettingsOut;
  onSettings: (settings: SettingsOut) => void;
}

function editingEnabled(settings: SettingsOut): boolean {
  return settings.rollout.local_settings_enabled && process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI === "1";
}

function readinessLabel(readiness: LlmStatusOut): string {
  if (readiness.available) return "Ready";
  if (!readiness.configured) return "Not configured";
  return "Unavailable";
}

export default function SettingsForm({ settings, onSettings }: SettingsFormProps) {
  const canEdit = editingEnabled(settings);
  const [provider, setProvider] = useState<"anthropic" | "ollama">(
    settings.provider === "ollama" ? "ollama" : "anthropic",
  );
  const [model, setModel] = useState(settings.model);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [status, setStatus] = useState<LlmStatusOut>(settings.readiness);
  const [message, setMessage] = useState<string | null>(null);
  const clearPhrase = `clear ${provider} credential`;

  async function handleSave() {
    const credentials: Record<string, string> = {};
    if (anthropicKey) credentials.anthropic_api_key = anthropicKey;
    if (ollamaBaseUrl) credentials.ollama_base_url = ollamaBaseUrl;
    const result = await saveSettings({ provider, model, credentials });
    if (result.data) {
      onSettings(result.data);
      setStatus(result.data.readiness);
      setMessage("Settings saved.");
      setAnthropicKey("");
      setOllamaBaseUrl("");
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

  return (
    <div className="flex flex-col gap-5">
      <section className="rounded-md border border-divider bg-surface-raised p-4">
        <h2 className="font-heading text-xl">AI Provider</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Provider
            <select
              value={provider}
              onChange={(event) => setProvider(event.target.value as "anthropic" | "ollama")}
              disabled={!canEdit}
              className="rounded-md border border-border bg-background p-2"
            >
              <option value="anthropic">anthropic</option>
              <option value="ollama">ollama</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            Model
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={!canEdit}
              className="rounded-md border border-border bg-background p-2"
            />
          </label>
        </div>
        <p className="mt-3 text-sm">
          Readiness: <strong>{readinessLabel(status)}</strong>
        </p>
        {status.remediation && <p className="mt-1 text-sm text-muted-foreground">{status.remediation}</p>}
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
              onChange={(event) => setOllamaBaseUrl(event.target.value)}
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
          <Button variant="primary" onClick={() => void handleSave()} disabled={!canEdit}>
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
