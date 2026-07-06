import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import CourseChatDrawer from "@/components/reader/CourseChatDrawer";
import { getChatHistory, sendChat } from "@/lib/api/client";
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

  it("a citation chip navigates using the structured section_id field — never parses source_ref — and closes the drawer", async () => {
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
    expect(onClose).toHaveBeenCalled();
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
});
