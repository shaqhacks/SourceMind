"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import Button from "@/components/ui/Button";

export interface ChatCitation {
  n: number;
  sectionId: string;
  page: number | null;
  sourceRef: string;
}

export interface ChatTurn {
  id: string;
  role: string;
  content: string;
  citations: ChatCitation[] | null;
}

export type ChatSendResult =
  | { ok: true; content: string; citations: ChatCitation[] }
  | { ok: false; message: string; retryable: boolean };

export interface ChatProps {
  /** Rejects (throws) on failure — Chat shows a load-error state with retry. */
  loadHistory: () => Promise<ChatTurn[]>;
  /** Never throws — reports failure via the `ok: false` branch instead. */
  sendFn: (message: string) => Promise<ChatSendResult>;
  onCitationClick?: (citation: ChatCitation) => void;
}

const THINKING_WRITING_DELAY_MS = 1500;

/**
 * Shared, API-agnostic chat transcript. Call sites own the actual network
 * calls (and any translation from their backend's response shape into
 * ChatTurn/ChatSendResult) and hand them in as `loadHistory`/`sendFn`.
 *
 * IMPORTANT — the v1 transcript-reset bug: `loadHistory` is a dependency
 * of this component's history-loading effect. If a call site passes an
 * inline arrow function, it's a new reference every render, the effect
 * re-fires, and the transcript visibly resets to "loading" mid-conversation.
 * Call sites MUST wrap both `loadHistory` and `sendFn` in `useCallback`
 * with stable dependencies.
 */
export default function Chat({ loadHistory, sendFn, onCitationClick }: ChatProps) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [historyState, setHistoryState] = useState<"loading" | "error" | "ready">("loading");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [thinkingStage, setThinkingStage] = useState<"searching" | "writing" | null>(null);
  const [sendError, setSendError] = useState<{ message: string; retryable: boolean } | null>(
    null,
  );
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null);

  // `historyState` already defaults to "loading" — no reset needed here.
  // (loadHistory is documented as stable, so this effect is expected to
  // run once per mount, not to react to it changing mid-lifecycle.)
  useEffect(() => {
    let active = true;
    loadHistory()
      .then((history) => {
        if (!active) return;
        setTurns(history);
        setHistoryState("ready");
      })
      .catch(() => {
        if (active) setHistoryState("error");
      });
    return () => {
      active = false;
    };
  }, [loadHistory]);

  function retryLoadHistory() {
    setHistoryState("loading");
    loadHistory()
      .then((history) => {
        setTurns(history);
        setHistoryState("ready");
      })
      .catch(() => setHistoryState("error"));
  }

  async function submit(message: string) {
    setSendError(null);
    setSending(true);
    setThinkingStage("searching");
    const writingTimer = setTimeout(() => setThinkingStage("writing"), THINKING_WRITING_DELAY_MS);

    const userTurn: ChatTurn = {
      id: `local-user-${Date.now()}`,
      role: "user",
      content: message,
      citations: null,
    };
    setTurns((prev) => [...prev, userTurn]);

    const result = await sendFn(message);
    clearTimeout(writingTimer);
    setThinkingStage(null);
    setSending(false);

    if (result.ok) {
      setLastFailedMessage(null);
      setTurns((prev) => [
        ...prev,
        {
          id: `local-assistant-${Date.now()}`,
          role: "assistant",
          content: result.content,
          citations: result.citations,
        },
      ]);
    } else {
      setLastFailedMessage(message);
      setSendError({ message: result.message, retryable: result.retryable });
      // The failed send still added a user turn above — drop it so retry
      // doesn't duplicate it once the resend succeeds and re-adds it.
      setTurns((prev) => prev.filter((turn) => turn.id !== userTurn.id));
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message || sending) return;
    setInput("");
    void submit(message);
  }

  function handleRetry() {
    if (lastFailedMessage) void submit(lastFailedMessage);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto p-4">
        {historyState === "loading" && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading conversation…
          </p>
        )}
        {historyState === "error" && (
          <ErrorBanner message="Could not load the conversation." onRetry={retryLoadHistory} />
        )}
        {historyState === "ready" && turns.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No messages yet — ask a question below.
          </p>
        )}
        {historyState === "ready" && turns.length > 0 && (
          <ul className="flex flex-col gap-4">
            {turns.map((turn) => (
              <li key={turn.id} className={turn.role === "user" ? "text-right" : "text-left"}>
                <div
                  className={`inline-block max-w-full rounded-lg px-3 py-2 text-left text-sm ${
                    turn.role === "user"
                      ? "bg-accent/10"
                      : "border border-border bg-background"
                  }`}
                >
                  <Markdown>{turn.content}</Markdown>
                  {turn.citations && turn.citations.length > 0 && (
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {turn.citations.map((citation) => (
                        <li key={citation.n}>
                          <button
                            type="button"
                            onClick={() => onCitationClick?.(citation)}
                            className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted-foreground/10"
                          >
                            [{citation.n}] {citation.sourceRef}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {thinkingStage && (
          <p role="status" className="mt-3 text-sm text-muted-foreground">
            {thinkingStage === "searching" ? "Searching your course text…" : "Writing…"}
          </p>
        )}

        {sendError && (
          <div className="mt-3">
            <ErrorBanner
              message={sendError.message}
              onRetry={sendError.retryable ? handleRetry : undefined}
            />
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t border-border p-3">
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          disabled={sending}
          placeholder="Ask about this course…"
          aria-label="Message"
          className="flex-1 rounded-md border border-border bg-transparent px-3 py-2 text-sm disabled:opacity-50"
        />
        <Button type="submit" variant="primary" disabled={sending || !input.trim()}>
          Send
        </Button>
      </form>
    </div>
  );
}
