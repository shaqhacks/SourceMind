import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import {
  checkLlmStatus,
  clearProviderSecret,
  discoverOllamaModels,
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
    discoverOllamaModels: vi.fn(),
  };
});

const mockedGetSettings = vi.mocked(getSettings);
const mockedCheckLlmStatus = vi.mocked(checkLlmStatus);
const mockedSaveSettings = vi.mocked(saveSettings);
const mockedClearProviderSecret = vi.mocked(clearProviderSecret);
const mockedDiscoverOllamaModels = vi.mocked(discoverOllamaModels);

const missingConfiguredModelMessage =
  "Your configured Ollama model “missing:latest” is not installed. Install it in Ollama or select another available model.";

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
    mockedDiscoverOllamaModels.mockResolvedValue({
      status: 200,
      ok: true,
      data: {
        models: ["gemma3:4b", "llama3.2:latest"],
        configured_model: "llama3.2:latest",
        configured_model_available: true,
      },
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
    expect(screen.queryByText("[redacted]")).not.toBeInTheDocument();
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

  it("enables settings controls from the backend rollout without the build-time UI flag", async () => {
    delete process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI;

    render(<SettingsPage />);

    expect(await screen.findByLabelText(/provider/i)).toBeEnabled();
    expect(screen.getByLabelText(/model/i)).toBeEnabled();
    expect(screen.getByLabelText(/anthropic api key/i)).toBeEnabled();
    expect(screen.getByLabelText(/ollama base url/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeEnabled();
  });

  it("clears all credential-like inputs after a successful save", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const anthropicInput = await screen.findByLabelText(/anthropic api key/i);
    const ollamaInput = screen.getByLabelText(/ollama base url/i);
    await user.type(anthropicInput, "sk-ant-new-secret");
    await user.type(ollamaInput, "http://127.0.0.1:11434");
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() => expect(mockedSaveSettings).toHaveBeenCalledTimes(1));
    expect(anthropicInput).toHaveValue("");
    expect(ollamaInput).toHaveValue("");
  });

  it("discovers Ollama models with the default first-time URL when switching providers", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");

    await waitFor(() => expect(mockedDiscoverOllamaModels).toHaveBeenCalledTimes(1));
    expect(mockedDiscoverOllamaModels).toHaveBeenCalledWith({
      base_url: "http://localhost:11434",
      configured_model: null,
    });
  });

  it("refreshes Ollama discovery on dropdown pointer interaction after the initial request", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");
    await waitFor(() => expect(mockedDiscoverOllamaModels).toHaveBeenCalledTimes(1));

    await user.pointer({ keys: "[MouseLeft>]", target: screen.getByLabelText(/model/i) });

    await waitFor(() => expect(mockedDiscoverOllamaModels).toHaveBeenCalledTimes(2));
  });

  it("coalesces concurrent Ollama discovery triggers while a request is in flight", async () => {
    const user = userEvent.setup();
    let resolveDiscovery: typeof mockedDiscoverOllamaModels extends { mockResolvedValue: (value: infer T) => unknown } ? (value: T) => void : never;
    const pendingDiscovery = new Promise<Awaited<ReturnType<typeof discoverOllamaModels>>>((resolve) => {
      resolveDiscovery = resolve;
    });
    mockedDiscoverOllamaModels.mockReturnValue(pendingDiscovery);
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");
    await user.pointer({ keys: "[MouseLeft>]", target: screen.getByLabelText(/model/i) });

    expect(mockedDiscoverOllamaModels).toHaveBeenCalledTimes(1);
    resolveDiscovery!({
      status: 200,
      ok: true,
      data: {
        models: ["gemma3:4b"],
        configured_model: null,
        configured_model_available: true,
      },
    });
  });

  it("ignores an in-flight Ollama discovery after switching back to Anthropic", async () => {
    const user = userEvent.setup();
    let resolveDiscovery: typeof mockedDiscoverOllamaModels extends { mockResolvedValue: (value: infer T) => unknown } ? (value: T) => void : never;
    const pendingDiscovery = new Promise<Awaited<ReturnType<typeof discoverOllamaModels>>>((resolve) => {
      resolveDiscovery = resolve;
    });
    mockedDiscoverOllamaModels.mockReturnValue(pendingDiscovery);
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");
    await user.selectOptions(screen.getByLabelText(/provider/i), "anthropic");

    expect(screen.getByLabelText(/provider/i)).toHaveValue("anthropic");
    expect(screen.getByLabelText(/model/i)).toHaveValue("claude-sonnet-4-5");

    resolveDiscovery!({
      status: 200,
      ok: true,
      data: {
        models: ["gemma3:4b"],
        configured_model: null,
        configured_model_available: true,
      },
    });
    await pendingDiscovery;

    expect(screen.getByLabelText(/model/i)).toHaveValue("claude-sonnet-4-5");
    expect(screen.queryByRole("option", { name: "gemma3:4b" })).not.toBeInTheDocument();
  });

  it("leaves a missing configured Ollama model absent, blank, and unsavable", async () => {
    mockedGetSettings.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSettings({
        provider: "ollama",
        model: "missing:latest",
        credentials_present: { anthropic: true, ollama: true },
        credentials: { anthropic_api_key: "[redacted]", ollama_base_url: "[redacted]" },
      }),
    });
    mockedDiscoverOllamaModels.mockResolvedValue({
      status: 200,
      ok: true,
      data: {
        models: ["gemma3:4b", "llama3.2:latest"],
        configured_model: "missing:latest",
        configured_model_available: false,
      },
    });

    render(<SettingsPage />);

    expect(await screen.findByText(missingConfiguredModelMessage)).toBeInTheDocument();
    const modelSelect = screen.getByLabelText(/model/i);
    expect(modelSelect).toHaveValue("");
    expect(screen.queryByRole("option", { name: "missing:latest" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });

  it.each([
    ["ollama_no_models", "Ollama did not report any completion-capable models."],
    ["ollama_no_completion_models", "Ollama did not report any completion-capable models."],
    ["ollama_invalid_url", "Ollama base URL must be an HTTP loopback origin."],
    ["ollama_timeout", "Ollama did not respond before the request timed out."],
    ["ollama_unreachable", "Ollama could not be reached."],
    ["ollama_invalid_response", "Ollama returned an invalid discovery response."],
  ])("shows safe Ollama discovery copy for %s without raw upstream details", async (category, message) => {
    const user = userEvent.setup();
    mockedDiscoverOllamaModels.mockResolvedValue({
      status: category === "ollama_invalid_response" ? 502 : 503,
      ok: false,
      error: {
        detail: {
          failure_category: category,
          message: `RAW UPSTREAM BODY: ${message}`,
        },
      },
    });
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText(/raw upstream body/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });

  it("clears Ollama model discovery when the base URL changes and rediscovers the edited URL", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");
    await waitFor(() => expect(mockedDiscoverOllamaModels).toHaveBeenCalledTimes(1));
    await user.selectOptions(screen.getByLabelText(/model/i), "gemma3:4b");
    await user.clear(screen.getByLabelText(/ollama base url/i));
    await user.type(screen.getByLabelText(/ollama base url/i), "http://127.0.0.1:11434");

    expect(screen.getByLabelText(/model/i)).toHaveValue("");
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();

    await user.pointer({ keys: "[MouseLeft>]", target: screen.getByLabelText(/model/i) });

    await waitFor(() => expect(mockedDiscoverOllamaModels).toHaveBeenLastCalledWith({
      base_url: "http://127.0.0.1:11434",
      configured_model: null,
    }));
  });

  it("saves Ollama settings only after selecting a currently discovered model", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.selectOptions(await screen.findByLabelText(/provider/i), "ollama");
    await waitFor(() => expect(mockedDiscoverOllamaModels).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText(/model/i), "llama3.2:latest");
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() => expect(mockedSaveSettings).toHaveBeenCalledTimes(1));
    expect(mockedSaveSettings).toHaveBeenCalledWith({
      provider: "ollama",
      model: "llama3.2:latest",
      credentials: { ollama_base_url: "http://localhost:11434" },
    });
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
    const fetchSpy = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
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
    await api.discoverOllamaModels({
      base_url: "http://localhost:11434",
      configured_model: "llama3.2:latest",
    });

    const requestBody = async (input: RequestInfo | URL, init?: RequestInit) => {
      if (input instanceof Request) {
        return input.body ? input.clone().json() : undefined;
      }
      if (typeof init?.body === "string") return JSON.parse(init.body);
      return init?.body;
    };
    const requests = await Promise.all(fetchSpy.mock.calls.map(async ([input, init]) => ({
      url: input instanceof Request ? input.url : String(input),
      method: input instanceof Request ? input.method : init?.method,
      cache: input instanceof Request ? input.cache : init?.cache,
      csrfToken: input instanceof Request
        ? input.headers.get("X-CSRF-Token")
        : new Headers(init?.headers).get("X-CSRF-Token"),
      body: await requestBody(input, init),
    })));

    expect(requests[0]).toMatchObject({ url: "http://localhost:8000/api/settings", method: "GET" });
    expect(fetchSpy).toHaveBeenNthCalledWith(2, "http://localhost:8000/api/settings/bootstrap", expect.objectContaining({ cache: "no-store" }));
    expect(requests[2]).toMatchObject({ url: "http://localhost:8000/api/settings", method: "PUT", csrfToken: "token-123" });
    expect(requests[3]).toMatchObject({ url: "http://localhost:8000/api/settings", method: "DELETE", csrfToken: "token-123" });
    expect(requests[4]).toMatchObject({
      url: "http://localhost:8000/api/settings/ollama/models",
      method: "POST",
      csrfToken: "token-123",
      body: {
        base_url: "http://localhost:11434",
        configured_model: "llama3.2:latest",
      },
    });
    expect(localStorage.getItem("csrf_token")).toBeNull();
    expect(sessionStorage.getItem("csrf_token")).toBeNull();
    expect(JSON.stringify(fetchSpy.mock.calls)).not.toContain("localStorage");
  });
});
