"use client";

import { useEffect, useLayoutEffect, useRef } from "react";

export type ShortcutMap = Record<string, (event: KeyboardEvent) => void>;

interface Scope {
  map: ShortcutMap;
}

// Scopes stack: the most recently registered enabled scope wins. This is
// what lets ShortcutsOverlay, once open, prevent the reader shell's
// shortcuts underneath it from also firing (e.g. arrow keys navigating
// chapters behind an open modal) without every caller having to
// coordinate an `enabled` flag with every other caller.
const scopes: Scope[] = [];
let listenerInstalled = false;

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return true;
  // Checking the attribute directly (rather than the isContentEditable IDL
  // property) also covers descendants of a contentEditable container, and
  // — unlike isContentEditable — jsdom actually implements it, so this is
  // testable as well as correct.
  return target.closest('[contenteditable]:not([contenteditable="false"])') !== null;
}

function normalizeKey(event: KeyboardEvent): string {
  const key = event.key.toLowerCase();
  if ((event.metaKey || event.ctrlKey) && key.length === 1) return `mod+${key}`;
  return key;
}

function handleGlobalKeyDown(event: KeyboardEvent): void {
  const key = normalizeKey(event);
  if (isEditableTarget(event.target) && key !== "escape") return;
  const topScope = scopes[scopes.length - 1];
  if (!topScope) return;
  const handler = topScope.map[key];
  if (handler) {
    handler(event);
  }
}

function ensureListener(): void {
  if (listenerInstalled) return;
  window.addEventListener("keydown", handleGlobalKeyDown);
  listenerInstalled = true;
}

/**
 * Registers `map` (lowercase event.key -> handler, e.g.
 * {"arrowright": onNext, "?": onOpenHelp}) as the active shortcut scope
 * while the calling component is mounted and `enabled` is true. Ignores
 * keydown events targeting inputs, textareas, or contentEditable elements
 * so shortcuts never fire while the user is typing.
 */
export function useKeyboardShortcuts(map: ShortcutMap, enabled = true): void {
  const scopeRef = useRef<Scope | null>(null);

  // `map` is deliberately excluded from this effect's deps — see the
  // effect below, which keeps scope.map fresh in place instead of
  // re-registering the scope's stack position on every render (callers
  // typically pass a new object literal each render).
  useIsomorphicLayoutEffect(() => {
    if (!enabled) return undefined;
    ensureListener();
    const scope: Scope = { map };
    scopeRef.current = scope;
    scopes.push(scope);
    return () => {
      const index = scopes.indexOf(scope);
      if (index !== -1) scopes.splice(index, 1);
      scopeRef.current = null;
    };
  }, [enabled]);

  useIsomorphicLayoutEffect(() => {
    if (scopeRef.current) {
      scopeRef.current.map = map;
    }
  }, [map]);
}
