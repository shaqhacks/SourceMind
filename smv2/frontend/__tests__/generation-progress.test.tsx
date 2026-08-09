import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import GenerationProgress from "@/components/jobs/GenerationProgress";
import type { JobEvent } from "@/lib/hooks/useJobEvents";

function job(overrides: Partial<JobEvent> = {}): JobEvent {
  return {
    id: "job-1",
    status: "running",
    progress: {
      stage: "thinking",
      pct: null,
      message: "Thinking · 4m 18s",
      elapsed_seconds: 258,
      last_activity_seconds: 0,
    },
    ...overrides,
  };
}

describe("GenerationProgress", () => {
  it("shows phase liveness without a fake percentage or reasoning text", () => {
    render(<GenerationProgress job={job()} quiet={false} />);

    expect(screen.getByText("Thinking · 4m 18s")).toBeInTheDocument();
    expect(screen.getByText(/model active/i)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/reasoning/i)).not.toBeInTheDocument();
  });

  it("switches to quiet copy after thirty seconds", () => {
    render(
      <GenerationProgress
        job={job({ progress: { ...job().progress!, elapsed_seconds: 31, message: "Thinking · 31s" } })}
        quiet={false}
      />,
    );

    expect(screen.getByText(/this can take a little while/i)).toBeInTheDocument();
  });

  it("calls cancel once and keeps the control keyboard reachable", async () => {
    let resolveCancel = () => {};
    const onCancel = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveCancel = resolve;
        }),
    );
    const user = userEvent.setup();

    render(<GenerationProgress job={job()} quiet={false} onCancel={onCancel} />);

    await user.tab();
    expect(screen.getByRole("button", { name: /cancel generation/i })).toHaveFocus();
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: /cancelling/i }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    resolveCancel();
  });

  it("continues in the background without cancelling", async () => {
    const onCancel = vi.fn();
    const onContinue = vi.fn();
    const user = userEvent.setup();

    render(
      <GenerationProgress
        job={job()}
        quiet={false}
        onCancel={onCancel}
        onContinue={onContinue}
      />,
    );

    await user.click(screen.getByRole("button", { name: /continue in background/i }));

    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("updates the polite live region only when the phase changes", async () => {
    const { rerender } = render(<GenerationProgress job={job()} quiet={false} />);

    expect(screen.getByRole("status")).toHaveTextContent("Thinking");

    rerender(
      <GenerationProgress
        job={job({ progress: { ...job().progress!, elapsed_seconds: 259, message: "Thinking · 4m 19s" } })}
        quiet={false}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Thinking");

    rerender(
      <GenerationProgress
        job={job({ progress: { ...job().progress!, stage: "finalizing", message: "Finalizing lesson · 4m 20s" } })}
        quiet={false}
      />,
    );

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Finalizing"));
  });
});
