import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import RecoveryBanner from "@/components/RecoveryBanner";
import type { ApiErrorDetail } from "@/lib/api/client";

const readinessDetails: ApiErrorDetail[] = [
  {
    code: "llm_readiness_unavailable",
    failure_category: "ollama_model_unavailable",
    message: "Your configured Ollama model is not present.",
    remediation: "Open Settings and select a currently installed model.",
  },
  {
    code: "llm_readiness_unavailable",
    failure_category: "missing_credentials",
    message: "Missing credentials.",
    remediation: "Open Settings and add a key.",
  },
  {
    code: "llm_readiness_unavailable",
    failure_category: "unknown_provider",
    message: "Unknown provider.",
    remediation: "Open Settings and choose a provider.",
  },
  {
    code: "llm_readiness_unavailable",
    failure_category: "unreachable",
    message: "Provider unreachable.",
    remediation: "Open Settings and verify the endpoint.",
  },
  {
    code: "llm_readiness_unavailable",
    failure_category: "ollama_embed_model_unavailable",
    message: "Your configured Ollama embedding model is not present.",
    remediation: "Open Settings and select a currently installed embedding model.",
  },
];

describe("RecoveryBanner", () => {
  afterEach(() => {
    cleanup();
  });

  it.each(readinessDetails)(
    "routes readiness category $failure_category to Settings without retry",
    async (detail) => {
      const onRetry = vi.fn();
      const user = userEvent.setup();

      render(
        <RecoveryBanner
          message={detail.message ?? "Provider is not ready."}
          errorDetail={detail}
          jobId="job-1"
          onRetry={onRetry}
        />,
      );

      expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute(
        "href",
        "/settings",
      );
      expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();

      await user.click(screen.getByRole("link", { name: /open settings/i }));
      expect(onRetry).not.toHaveBeenCalled();
    },
  );

  it("routes ordinary worker failures to job details and keeps retry available", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();

    render(
      <RecoveryBanner
        message="Generation failed."
        errorDetail={{ code: "worker_failed", message: "Generation failed." }}
        jobId="job-2"
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("link", { name: /view job details/i })).toHaveAttribute(
      "href",
      "/jobs?job=job-2",
    );
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
