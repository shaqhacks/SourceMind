"use client";

import { useTheme, type ThemePreference } from "@/lib/hooks/useTheme";

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function ThemeToggle() {
  const { preference, setPreference } = useTheme();

  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex overflow-hidden rounded-md border border-border text-sm"
    >
      {OPTIONS.map((option) => {
        const active = preference === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => setPreference(option.value)}
            className={`px-3 py-1.5 transition-colors ${
              active
                ? "bg-accent text-background"
                : "bg-transparent text-foreground hover:bg-foreground/[0.07]"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
