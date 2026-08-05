import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY,
  WORKSPACE_MODE_STORAGE_KEY,
  useWorkspaceMode,
} from "@/lib/hooks/useWorkspaceMode";

function WorkspaceHarness({ label = "primary" }: { label?: string }) {
  const { mode, setMode, toggle, disclosureSeen, markDisclosureSeen } = useWorkspaceMode();

  return (
    <section aria-label={label}>
      <output aria-label={`${label} mode`}>{mode}</output>
      <output aria-label={`${label} disclosure`}>
        {disclosureSeen ? "seen" : "unseen"}
      </output>
      <button type="button" onClick={() => setMode("instructor")}>
        Instructor
      </button>
      <button type="button" onClick={() => setMode("learner")}>
        Learner
      </button>
      <button type="button" onClick={toggle}>
        Toggle
      </button>
      {!disclosureSeen ? (
        <button type="button" onClick={markDisclosureSeen}>
          Dismiss instructor explanation
        </button>
      ) : null}
    </section>
  );
}

describe("useWorkspaceMode", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("persists the selected workspace mode across a remount", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<WorkspaceHarness />);

    expect(screen.getByLabelText("primary mode")).toHaveTextContent("learner");

    await user.click(screen.getByRole("button", { name: "Instructor" }));

    expect(screen.getByLabelText("primary mode")).toHaveTextContent("instructor");
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("instructor");

    unmount();
    render(<WorkspaceHarness />);

    expect(screen.getByLabelText("primary mode")).toHaveTextContent("instructor");
  });

  it("keeps multiple hook instances synced when one toggles the mode", async () => {
    const user = userEvent.setup();
    render(
      <>
        <WorkspaceHarness label="primary" />
        <WorkspaceHarness label="secondary" />
      </>,
    );

    await user.click(screen.getAllByRole("button", { name: "Toggle" })[0]);

    expect(screen.getByLabelText("primary mode")).toHaveTextContent("instructor");
    expect(screen.getByLabelText("secondary mode")).toHaveTextContent("instructor");
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("instructor");
  });

  it("ignores invalid stored modes and falls back to learner", () => {
    window.localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "admin");

    render(<WorkspaceHarness />);

    expect(screen.getByLabelText("primary mode")).toHaveTextContent("learner");
  });

  it("persists instructor disclosure independently from workspace mode", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<WorkspaceHarness />);

    expect(screen.getByLabelText("primary disclosure")).toHaveTextContent("unseen");
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Dismiss instructor explanation" }));

    expect(screen.getByLabelText("primary disclosure")).toHaveTextContent("seen");
    expect(window.localStorage.getItem(WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY)).toBe("true");
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBeNull();

    unmount();
    render(<WorkspaceHarness />);

    expect(screen.getByLabelText("primary disclosure")).toHaveTextContent("seen");
    expect(
      screen.queryByRole("button", { name: "Dismiss instructor explanation" }),
    ).not.toBeInTheDocument();
  });
});
