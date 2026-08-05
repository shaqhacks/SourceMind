"use client";

import { useCallback, useSyncExternalStore } from "react";

export type ShellLayout = "mobile" | "tablet" | "desktop";

const layoutListeners = new Set<() => void>();
const navigationListeners = new Set<() => void>();
let navigationOpen = false;

function layoutFromWidth(width: number): ShellLayout {
  if (width < 768) return "mobile";
  if (width < 1024) return "tablet";
  return "desktop";
}

function readLayout(): ShellLayout {
  if (typeof window === "undefined") return "desktop";
  return layoutFromWidth(window.innerWidth);
}

function subscribeLayout(onChange: () => void): () => void {
  layoutListeners.add(onChange);
  if (typeof window === "undefined") return () => layoutListeners.delete(onChange);

  const notify = () => {
    for (const listener of layoutListeners) listener();
  };
  const queries = [
    window.matchMedia("(max-width: 767px)"),
    window.matchMedia("(min-width: 768px) and (max-width: 1023px)"),
    window.matchMedia("(min-width: 1024px)"),
  ];

  window.addEventListener("resize", notify);
  queries.forEach((query) => query.addEventListener("change", notify));

  return () => {
    layoutListeners.delete(onChange);
    window.removeEventListener("resize", notify);
    queries.forEach((query) => query.removeEventListener("change", notify));
  };
}

function readNavigationOpen(): boolean {
  return navigationOpen;
}

function setNavigationOpen(open: boolean): void {
  if (navigationOpen === open) return;
  navigationOpen = open;
  for (const listener of navigationListeners) listener();
}

function subscribeNavigation(onChange: () => void): () => void {
  navigationListeners.add(onChange);
  return () => navigationListeners.delete(onChange);
}

export function useShellLayout(): ShellLayout {
  return useSyncExternalStore(subscribeLayout, readLayout, () => "desktop");
}

export function useShellNavigation() {
  const open = useSyncExternalStore(subscribeNavigation, readNavigationOpen, () => false);
  const openNavigation = useCallback(() => setNavigationOpen(true), []);
  const closeNavigation = useCallback(() => setNavigationOpen(false), []);
  const toggleNavigation = useCallback(() => setNavigationOpen(!readNavigationOpen()), []);

  return { open, openNavigation, closeNavigation, toggleNavigation };
}

