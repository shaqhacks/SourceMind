import { expect, test } from "@playwright/test";

import { attachPageErrorGuard, expectCleanPage, mockedSettings } from "./support/test-data";

test("Ollama provider only lists mocked completion models and warns on missing configured model", async ({
  page,
}) => {
  const errors = attachPageErrorGuard(page);
  const discoveredModels = ["llama3.2:latest", "mistral:latest"];
  let discoveryCalls = 0;

  await page.route("**/api/settings", (route) => route.fulfill({ json: mockedSettings("missing-model:latest") }));
  await page.route("**/api/settings/bootstrap", (route) => {
    return route.fulfill({ json: { csrf_token: "e2e-csrf-token", rollout: { local_settings_enabled: true } } });
  });
  await page.route("**/api/settings/ollama/models", async (route) => {
    discoveryCalls += 1;
    const body = route.request().postDataJSON() as { configured_model?: string | null };
    return route.fulfill({
      json: {
        models: discoveredModels,
        configured_model: body.configured_model ?? null,
        configured_model_available: discoveredModels.includes(body.configured_model ?? ""),
      },
    });
  });

  await page.goto("/settings");
  await expect(page.getByLabel("Provider")).toHaveValue("ollama");
  await expect(page.getByText(/Your configured Ollama model/)).toBeVisible();

  const modelSelect = page.getByLabel("Model");
  await modelSelect.focus();
  await modelSelect.click();
  await expect(modelSelect.locator("option")).toHaveText([
    "Select an installed model",
    "llama3.2:latest",
    "mistral:latest",
  ]);
  await expect(modelSelect.locator("option", { hasText: "missing-model:latest" })).toHaveCount(0);

  await modelSelect.selectOption("llama3.2:latest");
  await expect(modelSelect).toHaveValue("llama3.2:latest");
  expect(discoveryCalls, "dropdown focus/click triggers deterministic discovery").toBeGreaterThan(0);
  await expectCleanPage(errors);
});
