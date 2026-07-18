import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import CourseChatDrawer from "@/components/reader/CourseChatDrawer";
import { getChatHistory, sendChat, type ChatSelectionIn } from "@/lib/api/client";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

import { err, ok } from "./support/api-result";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/client", () => ({
  getChatHistory: vi.fn(),
  sendChat: vi.fn(),
}));

const mockedGetChatHistory = vi.mocked(getChatHistory);
const mockedSendChat = vi.mocked(sendChat);

// Mimics exactly how CourseReader wires the drawer: its own "c" shortcut
// toggling a local `open` state, passed down as a prop. CourseChatDrawer
// itself doesn't own the "c" key (only Escape) — this harness is what
// makes the toggle-via-reader-shell behavior testable in isolation here,
// without rendering the whole CourseReader tree.
function Harness({ courseId }: { courseId: string }) {
  const [open, setOpen] = useState(false);
  useKeyboardShortcuts({ c: () => setOpen((value) => !value) });
  return <CourseChatDrawer courseId={courseId} open={open} onClose={() => setOpen(false)} />;
}

// Mimics how CourseReader owns pendingSelection: a real, settable piece of
// state passed down as a prop, with onConsumeSelection wired back to clear
// it — needed to exercise "the selection attaches to exactly one turn"
// across two sends within a single render tree.
function SelectionHarness({
  courseId,
  initialSelection,
}: {
  courseId: string;
  initialSelection: ChatSelectionIn | null;
}) {
  const [pendingSelection, setPendingSelection] = useState<ChatSelectionIn | null>(
    initialSelection,
  );
  return (
    <CourseChatDrawer
      courseId={courseId}
      open
      onClose={vi.fn()}
      pendingSelection={pendingSelection}
      onConsumeSelection={() => setPendingSelection(null)}
    />
  );
}

describe("CourseChatDrawer", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    document.body.innerHTML = "";
  });

  it("renders chat history via the mocked client", async () => {
    mockedGetChatHistory.mockResolvedValue(
      ok([
        { id: "t1", role: "user", content: "Hello", citations: null, created_at: "2026-01-01T00:00:00Z" },
        {
          id: "t2",
          role: "assistant",
          content: "Hi there",
          citations: null,
          created_at: "2026-01-01T00:00:01Z",
        },
      ]),
    );

    render(<CourseChatDrawer courseId="course-1" open onClose={vi.fn()} />);

    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
    expect(mockedGetChatHistory).toHaveBeenCalledWith("course-1");
  });

  it("a citation chip navigates using the structured section_id field — never parses source_ref — and stays open (docked, wide viewport)", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    mockedSendChat.mockResolvedValue(
      ok({
        reply_md: "The answer is 42.",
        citations: [
          { n: 1, section_id: "sec-xyz", page: 5, source_ref: "totally-different-string:p.9" },
        ],
      }),
    );
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<CourseChatDrawer courseId="course-1" open onClose={onClose} />);
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "What is the answer?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    const chip = await screen.findByRole("button", { name: /totally-different-string:p\.9/i });
    await user.click(chip);

    // The chip's own label is the verbatim source_ref (display-only), but
    // navigation must use section_id, not anything parsed from that string.
    expect(mockPush).toHaveBeenCalledWith("/course/course-1?section=sec-xyz");
    // Docked panel: navigating via a citation doesn't lose the
    // conversation — only the narrow-viewport overlay fallback closes on
    // citation click (see the next test).
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a citation chip closes the panel on narrow viewports (overlay fallback)", async () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = ((query: string) =>
      ({
        matches: true,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList) as typeof window.matchMedia;

    mockedGetChatHistory.mockResolvedValue(ok([]));
    mockedSendChat.mockResolvedValue(
      ok({ reply_md: "The answer is 42.", citations: [{ n: 1, section_id: "sec-xyz", page: 5, source_ref: "ref:p.9" }] }),
    );
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<CourseChatDrawer courseId="course-1" open onClose={onClose} />);
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "What is the answer?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    const chip = await screen.findByRole("button", { name: /ref:p\.9/i });
    await user.click(chip);

    expect(mockPush).toHaveBeenCalledWith("/course/course-1?section=sec-xyz");
    expect(onClose).toHaveBeenCalled();

    window.matchMedia = originalMatchMedia;
  });

  it("'c' toggles the drawer open and closed, as wired by the reader shell", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    render(<Harness courseId="course-1" />);

    expect(screen.queryByRole("complementary", { name: /course chat/i })).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "c" });
    expect(await screen.findByRole("complementary", { name: /course chat/i })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "c" });
    expect(screen.queryByRole("complementary", { name: /course chat/i })).not.toBeInTheDocument();
  });

  it("Escape closes the drawer and restores focus to whatever had it before opening", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    const trigger = document.createElement("button");
    trigger.textContent = "Chat";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(trigger).toHaveFocus();

    const onClose = vi.fn();
    const { rerender } = render(<CourseChatDrawer courseId="course-1" open onClose={onClose} />);
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());
    expect(trigger).not.toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();

    // The parent reacts to onClose by flipping the `open` prop.
    rerender(<CourseChatDrawer courseId="course-1" open={false} onClose={onClose} />);
    expect(trigger).toHaveFocus();
  });

  it("a 429 shows a retryable 'Assistant is busy' banner", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    mockedSendChat.mockResolvedValue(err(429));
    const user = userEvent.setup();

    render(<CourseChatDrawer courseId="course-1" open onClose={vi.fn()} />);
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "Hello?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText(/assistant is busy — try again in a moment/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("sends without a selection by default — the no-selection path stays byte-identical", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    mockedSendChat.mockResolvedValue(ok({ reply_md: "Hi", citations: [] }));
    const user = userEvent.setup();

    render(<CourseChatDrawer courseId="course-1" open onClose={vi.fn()} />);
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "Hello?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => expect(mockedSendChat).toHaveBeenCalledWith("course-1", "Hello?"));
    expect(screen.queryByText(/asking about/i)).not.toBeInTheDocument();
  });

  it("shows a dismissible chip quoting the pending selection", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));

    render(
      <CourseChatDrawer
        courseId="course-1"
        open
        onClose={vi.fn()}
        pendingSelection={{ section_id: "s1", exact: "some text" }}
        onConsumeSelection={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    expect(screen.getByText(/asking about/i)).toHaveTextContent(/some text/i);
    expect(screen.getByRole("button", { name: /clear selected passage/i })).toBeInTheDocument();
  });

  it("truncates a long selection to roughly the first 60 characters in the chip", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    const longExact = "abcdefghij".repeat(10); // 100 chars

    render(
      <CourseChatDrawer
        courseId="course-1"
        open
        onClose={vi.fn()}
        pendingSelection={{ section_id: "s1", exact: longExact }}
        onConsumeSelection={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    const chip = screen.getByText(/asking about/i);
    expect(chip).not.toHaveTextContent(longExact);
    expect(chip.textContent?.length ?? 0).toBeLessThan(longExact.length);
  });

  it("the chip's ✕ calls onConsumeSelection without sending anything", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    const onConsumeSelection = vi.fn();
    const user = userEvent.setup();

    render(
      <CourseChatDrawer
        courseId="course-1"
        open
        onClose={vi.fn()}
        pendingSelection={{ section_id: "s1", exact: "some text" }}
        onConsumeSelection={onConsumeSelection}
      />,
    );
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: /clear selected passage/i }));

    expect(onConsumeSelection).toHaveBeenCalledTimes(1);
    expect(mockedSendChat).not.toHaveBeenCalled();
  });

  it("sends the pending selection with the next message, consumes it, and a second send carries none", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    mockedSendChat.mockResolvedValue(ok({ reply_md: "Reply", citations: [] }));
    const user = userEvent.setup();

    render(
      <SelectionHarness
        courseId="course-1"
        initialSelection={{ section_id: "s1", exact: "some text" }}
      />,
    );
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());
    expect(screen.getByText(/asking about/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/message/i), "Explain this");
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(mockedSendChat).toHaveBeenNthCalledWith(1, "course-1", "Explain this", {
        section_id: "s1",
        exact: "some text",
      }),
    );
    // Consumed after the successful send — the chip disappears.
    await waitFor(() => expect(screen.queryByText(/asking about/i)).not.toBeInTheDocument());

    await user.type(screen.getByLabelText(/message/i), "Second message");
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(mockedSendChat).toHaveBeenNthCalledWith(2, "course-1", "Second message"),
    );
  });

  it("a failed send does not consume the pending selection — retry still carries it", async () => {
    mockedGetChatHistory.mockResolvedValue(ok([]));
    mockedSendChat.mockResolvedValueOnce(err(429));
    mockedSendChat.mockResolvedValueOnce(ok({ reply_md: "Reply", citations: [] }));
    const onConsumeSelection = vi.fn();
    const user = userEvent.setup();

    render(
      <CourseChatDrawer
        courseId="course-1"
        open
        onClose={vi.fn()}
        pendingSelection={{ section_id: "s1", exact: "some text" }}
        onConsumeSelection={onConsumeSelection}
      />,
    );
    await waitFor(() => expect(mockedGetChatHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "Explain this");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/assistant is busy/i)).toBeInTheDocument();
    expect(onConsumeSelection).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() =>
      expect(mockedSendChat).toHaveBeenNthCalledWith(2, "course-1", "Explain this", {
        section_id: "s1",
        exact: "some text",
      }),
    );
    expect(onConsumeSelection).toHaveBeenCalledTimes(1);
  });
});
