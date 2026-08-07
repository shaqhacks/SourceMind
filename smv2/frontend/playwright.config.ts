import { defineConfig, devices } from "@playwright/test";
import { join } from "node:path";
import { tmpdir } from "node:os";

const backendPort = 8000;
const frontendPort = 3000;
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const e2eDataDir = process.env.SMV2_E2E_DATA_DIR ?? join(tmpdir(), "smv2-playwright-data");
const uvCacheDir = join(tmpdir(), "uv-cache");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: frontendUrl,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "rtk uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
      cwd: "../backend",
      url: `${backendUrl}/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        UV_CACHE_DIR: uvCacheDir,
        SMV2_DATA_DIR: e2eDataDir,
        SMV2_DB_URL: `sqlite:///${e2eDataDir}/smv2.db`,
        SMV2_BACKUPS_ENABLED: "0",
        SMV2_SAMPLE_COURSE_ENABLED: "0",
        SMV2_WORKER_ENABLED: "1",
        SMV2_HTML_CONVERSION: "0",
        SMV2_CORS_ORIGINS: frontendUrl,
      },
    },
    {
      command: "rtk npm run dev -- --hostname 127.0.0.1 --port 3000",
      url: frontendUrl,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        NEXT_PUBLIC_SMV2_API_URL: backendUrl,
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
});
