import vm from "node:vm";

import { afterEach, describe, expect, it, vi } from "vitest";

import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme/bootstrap";

interface BootstrapCase {
  name: string;
  stored: string | null;
  systemDark: boolean;
  expected: "light" | "dark";
}

const CASES: BootstrapCase[] = [
  { name: "stored dark overrides a light system", stored: "dark", systemDark: false, expected: "dark" },
  { name: "stored light overrides a dark system", stored: "light", systemDark: true, expected: "light" },
  { name: "stored system follows dark", stored: "system", systemDark: true, expected: "dark" },
  { name: "stored system follows light", stored: "system", systemDark: false, expected: "light" },
  { name: "missing preference follows the system", stored: null, systemDark: true, expected: "dark" },
  { name: "invalid preference falls back to the system", stored: "sepia", systemDark: false, expected: "light" },
];

describe("theme bootstrap", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it.each(CASES)("$name", ({ stored, systemDark, expected }) => {
    if (stored !== null) window.localStorage.setItem("smv2.theme", stored);
    const getItem = vi.spyOn(window.localStorage, "getItem");

    vm.runInNewContext(THEME_BOOTSTRAP_SCRIPT, {
      document,
      localStorage: window.localStorage,
      matchMedia: vi.fn(() => ({ matches: systemDark })),
    });

    expect(document.documentElement.dataset.theme).toBe(expected);
    expect(getItem).toHaveBeenCalledOnce();
    expect(getItem).toHaveBeenCalledWith("smv2.theme");
  });

  it("keeps the server-rendered fallback when storage access fails", () => {
    document.documentElement.dataset.theme = "light";

    expect(() =>
      vm.runInNewContext(THEME_BOOTSTRAP_SCRIPT, {
        document,
        localStorage: {
          getItem: () => {
            throw new Error("storage unavailable");
          },
        },
        matchMedia: vi.fn(() => ({ matches: true })),
      }),
    ).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
