import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

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
  },
});
