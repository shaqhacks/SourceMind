import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import {
  checkLlmStatus,
  clearProviderSecret,
  getSettings,
  saveSettings,
  type SettingsOut,
} from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    getSettings: vi.fn(),
    checkLlmStatus: vi.fn(),
    saveSettings: vi.fn(),
    clearProviderSecret: vi.fn(),
  };
});

const mockedGetSettings = vi.mocked(getSettings);
const mockedCheckLlmStatus = vi.mocked(checkLlmStatus);
const mockedSaveSettings = vi.mocked(saveSettings);
const mockedClearProviderSecret = vi.mocked(clearProviderSecret);

function makeSettings(overrides: Partial<SettingsOut> = {}): SettingsOut {
  return {
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    credentials_present: { anthropic: true, ollama: false },
    credentials: { anthropic_api_key: "[redacted]" },
    rollout: { local_settings_enabled: true },
    readiness: {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      configured: true,
      available: true,
      capabilities: { completion: true, embeddings: false },
      last_checked_at: "2026-08-05T12:00:00Z",
      failure_category: null,
      remediation: null,
    },
    ...overrides,
  };
}

describe("SettingsPage", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI = "1";
    mockedGetSettings.mockResolvedValue({ status: 200, ok: true, data: makeSettings() });
    mockedCheckLlmStatus.mockResolvedValue({ status: 200, ok: true, data: makeSettings().readiness });
    mockedSaveSettings.mockResolvedValue({ status: 200, ok: true, data: makeSettings({ model: "claude-opus-4-1" }) });
    mockedClearProviderSecret.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSettings({
        credentials_present: { anthropic: false, ollama: false },
        credentials: {},
      }),
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    delete process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI;
  });

  it("shows provider, model, readiness, and redacted credential state", async () => {
    render(<SettingsPage />);

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("anthropic")).toBeInTheDocument();
    expect(screen.getByDisplayValue("claude-sonnet-4-5")).toBeInTheDocument();
    expect(screen.getByText(/ready/i)).toBeInTheDocument();
    expect(screen.getByText(/anthropic credential saved/i)).toBeInTheDocument();
    expect(screen.getByText("[redacted]")).toBeInTheDocument();
  });

  it("tests the configured connection without saving credentials", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole("button", { name: /test connection/i }));

    expect(mockedCheckLlmStatus).toHaveBeenCalledTimes(1);
    expect(mockedSaveSettings).not.toHaveBeenCalled();
    expect(await screen.findByText(/connection available/i)).toBeInTheDocument();
  });

  it("requires the exact confirmation phrase before clearing a provider credential", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole("button", { name: /clear anthropic credential/i }));
    expect(mockedClearProviderSecret).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/confirmation/i), "clear anthropic credential");
    await user.click(screen.getByRole("button", { name: /clear anthropic credential/i }));

    expect(mockedClearProviderSecret).toHaveBeenCalledWith("anthropic", "clear anthropic credential");
  });

  it("keeps credential inputs disabled when the rollout flag is off", async () => {
    process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI = "0";

    render(<SettingsPage />);

    expect(await screen.findByLabelText(/anthropic api key/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });
});

describe("settings CSRF helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("fetches the bootstrap token with no-store, keeps it out of browser storage, and sends it only on mutations", async () => {
    vi.resetModules();
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.endsWith("/api/settings/bootstrap")) {
        return new Response(JSON.stringify({ csrf_token: "token-123", rollout: { local_settings_enabled: true } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(makeSettings()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    const api = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");

    await api.getSettings();
    await api.saveSettings({ provider: "anthropic", model: "claude", credentials: {} });
    await api.clearProviderSecret("anthropic", "clear anthropic credential");

    const requests = fetchSpy.mock.calls.map(([input, init]) => ({
      url: input instanceof Request ? input.url : String(input),
      method: input instanceof Request ? input.method : init?.method,
      cache: input instanceof Request ? input.cache : init?.cache,
      csrfToken: input instanceof Request
        ? input.headers.get("X-CSRF-Token")
        : new Headers(init?.headers).get("X-CSRF-Token"),
    }));

    expect(requests[0]).toMatchObject({ url: "http://localhost:8000/api/settings", method: "GET" });
    expect(fetchSpy).toHaveBeenNthCalledWith(2, "http://localhost:8000/api/settings/bootstrap", expect.objectContaining({ cache: "no-store" }));
    expect(requests[2]).toMatchObject({ url: "http://localhost:8000/api/settings", method: "PUT", csrfToken: "token-123" });
    expect(requests[3]).toMatchObject({ url: "http://localhost:8000/api/settings", method: "DELETE", csrfToken: "token-123" });
    expect(localStorage.getItem("csrf_token")).toBeNull();
    expect(sessionStorage.getItem("csrf_token")).toBeNull();
    expect(JSON.stringify(fetchSpy.mock.calls)).not.toContain("localStorage");
  });
});
