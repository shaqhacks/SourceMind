import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  // Vitest (unlike Next.js) doesn't read tsconfig `paths` on its own —
  // mirror the "@/*" alias here explicitly.
  resolve: {
    alias: {
      "@": dirname,
    },
  },
  test: {
    environment: "jsdom",
    // jsdom defaults to the opaque "about:blank" origin, which makes it
    // throw `SecurityError: localStorage is not available for opaque
    // origins` — several hooks here (useTheme, useTypographyPrefs) persist
    // to localStorage, so tests need a real origin to run against.
    environmentOptions: {
      jsdom: {
        url: "http://localhost/",
      },
    },
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    exclude: [...configDefaults.exclude, "e2e/**", "test-results/**"],
    // @testing-library/dom's default asyncUtilTimeout (1000ms, set in
    // vitest.setup.ts) is well under vitest's own 5000ms default — under
    // CPU contention (many worker threads/processes competing for cores,
    // e.g. a busy CI runner), individual findBy*/waitFor calls can
    // legitimately take longer than 1000ms even though nothing is
    // actually hung, which manifested as flaky "Unable to find ..."
    // failures on a different, effectively random test each run. Raised
    // to 10s here so a real hang still fails within one test run, with
    // enough headroom over asyncUtilTimeout's 5s that the more specific
    // "unable to find X" error surfaces before this cruder timeout would.
    testTimeout: 10000,
  },
});
