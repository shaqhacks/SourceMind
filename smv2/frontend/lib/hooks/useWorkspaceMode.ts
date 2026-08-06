"use client";

import { useCallback, useSyncExternalStore } from "react";

export const WORKSPACE_MODE_STORAGE_KEY = "smv2.workspaceMode";
export const WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY = "smv2.workspaceModeDisclosureSeen";

export type WorkspaceMode = "learner" | "instructor";

const DEFAULT_MODE: WorkspaceMode = "learner";

function isWorkspaceMode(value: string | null): value is WorkspaceMode {
  return value === "learner" || value === "instructor";
}

function readStoredMode(): WorkspaceMode {
  if (typeof window === "undefined") return DEFAULT_MODE;
  try {
    const raw = window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY);
    return isWorkspaceMode(raw) ? raw : DEFAULT_MODE;
  } catch {
    return DEFAULT_MODE;
  }
}

function readDisclosureSeen(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function getModeServerSnapshot(): WorkspaceMode {
  return DEFAULT_MODE;
}

function getDisclosureServerSnapshot(): boolean {
  return false;
}

const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function notify(): void {
  for (const listener of listeners) listener();
}

function persistMode(mode: WorkspaceMode): void {
  if (!isWorkspaceMode(mode)) return;
  try {
    window.localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  } catch {
    // Best-effort: blocked or full localStorage should not break navigation.
  }
  notify();
}

function persistDisclosureSeen(): void {
  try {
    window.localStorage.setItem(WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY, "true");
  } catch {
    // Best-effort: the explanation can reappear if persistence is unavailable.
  }
  notify();
}

export interface UseWorkspaceModeResult {
  mode: WorkspaceMode;
  setMode: (mode: WorkspaceMode) => void;
  toggle: () => void;
  disclosureSeen: boolean;
  markDisclosureSeen: () => void;
}

export function useWorkspaceMode(): UseWorkspaceModeResult {
  const mode = useSyncExternalStore(subscribe, readStoredMode, getModeServerSnapshot);
  const disclosureSeen = useSyncExternalStore(
    subscribe,
    readDisclosureSeen,
    getDisclosureServerSnapshot,
  );
  const setMode = useCallback((next: WorkspaceMode) => persistMode(next), []);
  const toggle = useCallback(
    () => persistMode(readStoredMode() === "learner" ? "instructor" : "learner"),
    [],
  );
  const markDisclosureSeen = useCallback(() => persistDisclosureSeen(), []);

  return { mode, setMode, toggle, disclosureSeen, markDisclosureSeen };
}
