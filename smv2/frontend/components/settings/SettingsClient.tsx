"use client";

import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import SettingsForm from "@/components/settings/SettingsForm";
import { describeError, type FetchError } from "@/lib/api/errors";
import { getSettings, type SettingsOut } from "@/lib/api/client";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; settings: SettingsOut };

export default function SettingsClient() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(() => {
    getSettings().then(({ data, status }) => {
      if (data) setState({ kind: "ready", settings: data });
      else setState({ kind: "error", error: describeError(status, "Loading settings") });
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-3xl">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Provider readiness and local credentials.</p>
      </div>
      {state.kind === "loading" && <p role="status">Loading settings...</p>}
      {state.kind === "error" && (
        <ErrorBanner status={state.error.status} message={state.error.message} onRetry={load} />
      )}
      {state.kind === "ready" && (
        <SettingsForm settings={state.settings} onSettings={((settings) => setState({ kind: "ready", settings }))} />
      )}
    </div>
  );
}
