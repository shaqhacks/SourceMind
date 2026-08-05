import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CurriculumReviewPage from "@/app/course/[courseId]/curriculum/page";
import DiagnosticValidationPage from "@/app/course/[courseId]/diagnostics/validate/page";
import {
  WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY,
  WORKSPACE_MODE_STORAGE_KEY,
  useWorkspaceMode,
} from "@/lib/hooks/useWorkspaceMode";

vi.mock("@/components/curriculum/CurriculumReview", () => ({
  default: ({ courseId }: { courseId: string }) => (
    <section>Curriculum review content for {courseId}</section>
  ),
}));

vi.mock("@/components/diagnostics/DiagnosticValidation", () => ({
  default: ({ courseId }: { courseId: string }) => (
    <section>Diagnostic validation content for {courseId}</section>
  ),
}));

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

describe("WorkspaceModeGate", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("explains learner mode on direct curriculum navigation without rendering instructor content", async () => {
    const element = await CurriculumReviewPage({
      params: Promise.resolve({ courseId: "course-1" }),
    });

    render(element);

    expect(
      screen.getByRole("region", { name: "Instructor workspace is hidden" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Instructor workspace is hidden" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/learner mode keeps curriculum review and diagnostics out of the main study flow/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/local display preference/i)).toBeInTheDocument();
    expect(screen.getByText(/not a security boundary/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to course" })).toHaveAttribute(
      "href",
      "/course/course-1",
    );
    expect(
      screen.queryByText("Curriculum review content for course-1"),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBeNull();
  });

  it("explains learner mode on direct diagnostic validation navigation", async () => {
    const element = await DiagnosticValidationPage({
      params: Promise.resolve({ courseId: "course-2" }),
    });

    render(element);

    expect(
      screen.getByRole("heading", { name: "Instructor workspace is hidden" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to course" })).toHaveAttribute(
      "href",
      "/course/course-2",
    );
    expect(
      screen.queryByText("Diagnostic validation content for course-2"),
    ).not.toBeInTheDocument();
  });

  it("switches to instructor mode in place and reveals the requested curriculum route", async () => {
    const user = userEvent.setup();
    const element = await CurriculumReviewPage({
      params: Promise.resolve({ courseId: "course-1" }),
    });

    render(element);

    await user.click(screen.getByRole("button", { name: "Switch to Instructor mode" }));

    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("instructor");
    expect(
      screen.queryByRole("heading", { name: "Instructor workspace is hidden" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Curriculum review content for course-1")).toBeInTheDocument();
  });

  it("switches to instructor mode in place and reveals the requested validation route", async () => {
    const user = userEvent.setup();
    const element = await DiagnosticValidationPage({
      params: Promise.resolve({ courseId: "course-2" }),
    });

    render(element);

    await user.click(screen.getByRole("button", { name: "Switch to Instructor mode" }));

    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("instructor");
    expect(
      screen.queryByRole("heading", { name: "Instructor workspace is hidden" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Diagnostic validation content for course-2")).toBeInTheDocument();
  });
});
