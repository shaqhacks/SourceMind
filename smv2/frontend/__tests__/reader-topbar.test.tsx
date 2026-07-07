import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TopBar, { type TopBarProps } from "@/components/reader/TopBar";
import { listTests } from "@/lib/api/client";

import { ok } from "./support/api-result";

// QuizzesPanel (mounted by TopBar) uses next/navigation + the api client;
// GenerateAllLessons uses the api client too. Mirror the mocks those
// components' own unit tests use so TopBar can mount them for real.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listTests: vi.fn(),
  generateTest: vi.fn(),
  generateAllLessons: vi.fn(),
  getJob: vi.fn(),
}));

const realMatchMedia = window.matchMedia;

// useNarrowViewport builds `(max-width: 1023px)`; drive its result by making
// matchMedia report `matches` for that max-width query.
function mockViewport(narrow: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: narrow && query.includes("max-width"),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => true,
  })) as unknown as typeof window.matchMedia;
}

function makeProps(overrides: Partial<TopBarProps> = {}): TopBarProps {
  return {
    courseId: "course-1",
    courseTitle: "Test Course",
    sidebarCollapsed: false,
    onToggleSidebar: vi.fn(),
    onLessonSectionSettled: vi.fn(),
    chatOpen: false,
    onToggleChat: vi.fn(),
    onOpenOutlineEditor: vi.fn(),
    viewMode: "source",
    pagesAvailable: false,
    onChangeViewMode: vi.fn(),
    ...overrides,
  };
}

describe("reader TopBar", () => {
  beforeEach(() => {
    vi.mocked(listTests).mockResolvedValue(ok([]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.matchMedia = realMatchMedia;
  });

  it("does not render a theme toggle — the global site header owns theme now", () => {
    mockViewport(false);
    render(<TopBar {...makeProps()} />);

    expect(screen.queryByRole("group", { name: /theme/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "System" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Light" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dark" })).not.toBeInTheDocument();
  });

  it("renders the mid-bar actions inline at lg and up, with no overflow menu", () => {
    mockViewport(false);
    render(<TopBar {...makeProps()} />);

    expect(screen.getByRole("button", { name: /edit outline/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate all lessons/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /quizzes/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /more actions/i })).not.toBeInTheDocument();
  });

  it("collapses the mid-bar actions into an overflow menu below lg", async () => {
    mockViewport(true);
    const user = userEvent.setup();
    render(<TopBar {...makeProps()} />);

    // Collapsed: only the trigger is present; the actions live behind it.
    const trigger = screen.getByRole("button", { name: /more actions/i });
    expect(trigger).toHaveAttribute("aria-haspopup", "true");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /edit outline/i })).not.toBeInTheDocument();

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /edit outline/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate all lessons/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /quizzes/i })).toBeInTheDocument();
  });

  it("closes the overflow menu on Escape and returns focus to the trigger", async () => {
    mockViewport(true);
    const user = userEvent.setup();
    render(<TopBar {...makeProps()} />);

    const trigger = screen.getByRole("button", { name: /more actions/i });
    await user.click(trigger);
    expect(screen.getByRole("button", { name: /edit outline/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /edit outline/i })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes the overflow menu on an outside pointer click", async () => {
    mockViewport(true);
    const user = userEvent.setup();
    render(<TopBar {...makeProps()} />);

    const trigger = screen.getByRole("button", { name: /more actions/i });
    await user.click(trigger);
    expect(screen.getByRole("button", { name: /edit outline/i })).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /edit outline/i })).not.toBeInTheDocument();
  });

  it("selecting Edit outline from the menu invokes the handler and closes the menu", async () => {
    mockViewport(true);
    const user = userEvent.setup();
    const onOpenOutlineEditor = vi.fn();
    render(<TopBar {...makeProps({ onOpenOutlineEditor })} />);

    const trigger = screen.getByRole("button", { name: /more actions/i });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: /edit outline/i }));

    expect(onOpenOutlineEditor).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /edit outline/i })).not.toBeInTheDocument();
  });
});
