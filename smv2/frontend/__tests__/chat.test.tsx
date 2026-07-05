import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Chat, { type ChatSendResult, type ChatTurn } from "@/components/Chat";

describe("Chat", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("loads and renders history", async () => {
    const loadHistory = vi.fn<() => Promise<ChatTurn[]>>().mockResolvedValue([
      { id: "t1", role: "user", content: "Hello", citations: null },
      { id: "t2", role: "assistant", content: "Hi there", citations: null },
    ]);
    const sendFn = vi.fn();

    render(<Chat loadHistory={loadHistory} sendFn={sendFn} />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading conversation/i);
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });

  it("names the next action when there's no history yet, instead of a blank panel", async () => {
    const loadHistory = vi.fn<() => Promise<ChatTurn[]>>().mockResolvedValue([]);
    const sendFn = vi.fn();

    render(<Chat loadHistory={loadHistory} sendFn={sendFn} />);

    expect(await screen.findByText(/no messages yet/i)).toBeInTheDocument();
  });

  it("shows a retryable error banner on history load failure, and retry recovers", async () => {
    const loadHistory = vi
      .fn<() => Promise<ChatTurn[]>>()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce([{ id: "t1", role: "assistant", content: "Recovered", citations: null }]);
    const sendFn = vi.fn();
    const user = userEvent.setup();

    render(<Chat loadHistory={loadHistory} sendFn={sendFn} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load the conversation/i);
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Recovered")).toBeInTheDocument();
  });

  it("sends a message optimistically, then renders the reply with a citation chip", async () => {
    const loadHistory = vi.fn<() => Promise<ChatTurn[]>>().mockResolvedValue([]);
    const sendFn = vi.fn<(message: string) => Promise<ChatSendResult>>().mockResolvedValue({
      ok: true,
      content: "The answer is 42.",
      citations: [{ n: 1, sectionId: "sec-1", page: 5, sourceRef: "sec-1:p.5" }],
    });
    const onCitationClick = vi.fn();
    const user = userEvent.setup();

    render(<Chat loadHistory={loadHistory} sendFn={sendFn} onCitationClick={onCitationClick} />);
    await waitFor(() => expect(loadHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "What is the answer?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(screen.getByText("What is the answer?")).toBeInTheDocument();
    expect(sendFn).toHaveBeenCalledWith("What is the answer?");

    expect(await screen.findByText(/the answer is 42/i)).toBeInTheDocument();
    const chip = screen.getByRole("button", { name: /sec-1:p\.5/i });
    await user.click(chip);
    expect(onCitationClick).toHaveBeenCalledWith({
      n: 1,
      sectionId: "sec-1",
      page: 5,
      sourceRef: "sec-1:p.5",
    });
  });

  it("shows the 'searching' then 'writing' thinking stages while awaiting a reply", async () => {
    const loadHistory = vi.fn<() => Promise<ChatTurn[]>>().mockResolvedValue([]);
    let resolveSend: (value: ChatSendResult) => void = () => {};
    const sendFn = vi.fn(
      () =>
        new Promise<ChatSendResult>((resolve) => {
          resolveSend = resolve;
        }),
    );

    render(<Chat loadHistory={loadHistory} sendFn={sendFn} />);
    await waitFor(() => expect(loadHistory).toHaveBeenCalled());

    vi.useFakeTimers();
    fireEvent.change(screen.getByLabelText(/message/i), { target: { value: "Hi" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/searching your course text/i);

    act(() => {
      vi.advanceTimersByTime(1500);
    });

    expect(screen.getByRole("status")).toHaveTextContent(/writing/i);

    await act(async () => {
      resolveSend({ ok: true, content: "Done.", citations: [] });
      await Promise.resolve();
    });
  });

  it("on send failure, shows a retryable error and resends the same message on retry (without duplicating it)", async () => {
    const loadHistory = vi.fn<() => Promise<ChatTurn[]>>().mockResolvedValue([]);
    const sendFn = vi
      .fn<(message: string) => Promise<ChatSendResult>>()
      .mockResolvedValueOnce({
        ok: false,
        message: "Assistant is busy — try again in a moment.",
        retryable: true,
      })
      .mockResolvedValueOnce({ ok: true, content: "Now it works.", citations: [] });
    const user = userEvent.setup();

    render(<Chat loadHistory={loadHistory} sendFn={sendFn} />);
    await waitFor(() => expect(loadHistory).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/message/i), "Retry me");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/assistant is busy/i)).toBeInTheDocument();
    expect(screen.queryByText("Retry me")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(sendFn).toHaveBeenLastCalledWith("Retry me");
    expect(await screen.findByText(/now it works/i)).toBeInTheDocument();
  });

  it("does not reset the transcript when loadHistory/sendFn keep stable references across re-renders", async () => {
    const loadHistory = vi.fn<() => Promise<ChatTurn[]>>().mockResolvedValue([]);
    const sendFn = vi
      .fn<(message: string) => Promise<ChatSendResult>>()
      .mockResolvedValue({ ok: true, content: "Reply", citations: [] });
    const user = userEvent.setup();

    const { rerender } = render(<Chat loadHistory={loadHistory} sendFn={sendFn} />);
    await waitFor(() => expect(loadHistory).toHaveBeenCalledTimes(1));

    await user.type(screen.getByLabelText(/message/i), "Ping");
    await user.click(screen.getByRole("button", { name: /send/i }));
    expect(await screen.findByText(/reply/i)).toBeInTheDocument();

    // Parent re-renders with the SAME function references (as documented)
    // — the transcript must not reload/reset.
    rerender(<Chat loadHistory={loadHistory} sendFn={sendFn} />);
    expect(loadHistory).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Ping")).toBeInTheDocument();
    expect(screen.getByText(/reply/i)).toBeInTheDocument();
  });

  it("resets the transcript (the v1 bug) when a call site passes a new loadHistory reference every render", async () => {
    const sendFn = vi.fn();
    const firstLoad = vi
      .fn<() => Promise<ChatTurn[]>>()
      .mockResolvedValue([{ id: "t1", role: "assistant", content: "First load", citations: null }]);
    const secondLoad = vi
      .fn<() => Promise<ChatTurn[]>>()
      .mockResolvedValue([{ id: "t2", role: "assistant", content: "Second load", citations: null }]);

    const { rerender } = render(<Chat loadHistory={firstLoad} sendFn={sendFn} />);
    expect(await screen.findByText("First load")).toBeInTheDocument();

    rerender(<Chat loadHistory={secondLoad} sendFn={sendFn} />);
    expect(await screen.findByText("Second load")).toBeInTheDocument();
    expect(secondLoad).toHaveBeenCalledTimes(1);
  });
});
