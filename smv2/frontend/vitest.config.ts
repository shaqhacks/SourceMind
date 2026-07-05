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
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
});
