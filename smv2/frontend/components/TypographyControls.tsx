"use client";

import { useEffect, useRef, useState } from "react";

import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import {
  FONT_SIZE_RANGE,
  LINE_HEIGHT_RANGE,
  MEASURE_RANGE,
  useTypographyPrefs,
} from "@/lib/hooks/useTypographyPrefs";

const PANEL_ID = "typography-controls-panel";

export default function TypographyControls() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useDialogFocus<HTMLDivElement>(open, { trap: false });
  const { prefs, setFontSize, setMeasure, setLineHeight } = useTypographyPrefs();

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    function handlePointerDown(event: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={PANEL_ID}
        aria-label="Typography settings"
        onClick={() => setOpen((value) => !value)}
        className="rounded-md border border-border px-3 py-1.5 text-sm font-serif"
      >
        Aa
      </button>
      {open && (
        <div
          ref={panelRef}
          id={PANEL_ID}
          role="group"
          aria-label="Typography settings"
          tabIndex={-1}
          className="absolute right-0 z-10 mt-2 w-64 space-y-4 rounded-md border border-border bg-background p-4 text-sm shadow-lg"
        >
          <label className="block">
            <span className="mb-1 flex justify-between text-muted-foreground">
              <span>Font size</span>
              <span>{prefs.fontSize}px</span>
            </span>
            <input
              type="range"
              aria-label="Font size"
              min={FONT_SIZE_RANGE.min}
              max={FONT_SIZE_RANGE.max}
              step={1}
              value={prefs.fontSize}
              onChange={(event) => setFontSize(Number(event.target.value))}
              className="w-full"
            />
          </label>
          <label className="block">
            <span className="mb-1 flex justify-between text-muted-foreground">
              <span>Line width</span>
              <span>{prefs.measure}ch</span>
            </span>
            <input
              type="range"
              aria-label="Line width"
              min={MEASURE_RANGE.min}
              max={MEASURE_RANGE.max}
              step={1}
              value={prefs.measure}
              onChange={(event) => setMeasure(Number(event.target.value))}
              className="w-full"
            />
          </label>
          <label className="block">
            <span className="mb-1 flex justify-between text-muted-foreground">
              <span>Line height</span>
              <span>{prefs.lineHeight.toFixed(1)}</span>
            </span>
            <input
              type="range"
              aria-label="Line height"
              min={LINE_HEIGHT_RANGE.min}
              max={LINE_HEIGHT_RANGE.max}
              step={0.1}
              value={prefs.lineHeight}
              onChange={(event) => setLineHeight(Number(event.target.value))}
              className="w-full"
            />
          </label>
        </div>
      )}
    </div>
  );
}
