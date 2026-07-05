"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

import Chat, { type ChatCitation, type ChatSendResult, type ChatTurn } from "@/components/Chat";
import { getChatHistory, sendChat, type ChatTurnOut } from "@/lib/api/client";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface CourseChatDrawerProps {
  courseId: string;
  open: boolean;
  onClose: () => void;
}

/** ChatTurnOut.citations is `{[key:string]: unknown}[] | null` (untyped —
 * history rows store raw citation dicts), unlike ChatOut.citations
 * (typed ChatCitationOut[] for a fresh send). Narrow defensively. */
function parseCitation(raw: unknown): ChatCitation | null {
  if (typeof raw !== "object" || raw === null) return null;
  const record = raw as Record<string, unknown>;
  const { n, section_id: sectionId, source_ref: sourceRef, page } = record;
  if (
    typeof n === "number" &&
    typeof sectionId === "string" &&
    typeof sourceRef === "string" &&
    (page === null || typeof page === "number" || page === undefined)
  ) {
    return { n, sectionId, sourceRef, page: (page as number | null | undefined) ?? null };
  }
  return null;
}

function mapTurn(turn: ChatTurnOut): ChatTurn {
  return {
    id: turn.id,
    role: turn.role,
    content: turn.content,
    citations: turn.citations
      ? turn.citations.map(parseCitation).filter((citation): citation is ChatCitation => citation !== null)
      : null,
  };
}

function describeSendError(status: number | undefined): { message: string; retryable: boolean } {
  if (status === 429) {
    return { message: "Assistant is busy — try again in a moment.", retryable: true };
  }
  if (status === 504) {
    return { message: "The assistant took too long to respond.", retryable: true };
  }
  if (status === undefined) {
    return { message: "Could not reach the assistant.", retryable: true };
  }
  return { message: `The assistant failed (HTTP ${status}).`, retryable: status >= 500 };
}

/**
 * Course-chat wiring around the shared, API-agnostic Chat component:
 * translates send_chat/chat_history into Chat's props, and turns a
 * citation click into a reader navigation (using the structured
 * section_id field — source_ref is display-only and never parsed).
 */
export default function CourseChatDrawer({ courseId, open, onClose }: CourseChatDrawerProps) {
  const router = useRouter();

  // Own "escape" scope while open, same pattern as ShortcutsOverlay: sits
  // on top of the reader's arrow/j/k/s scope so those don't fire behind
  // an open drawer.
  useKeyboardShortcuts({ escape: onClose }, open);

  const loadHistory = useCallback(async () => {
    const { data } = await getChatHistory(courseId);
    if (!data) throw new Error("Failed to load chat history");
    return data.map(mapTurn);
  }, [courseId]);

  const sendFn = useCallback(
    async (message: string): Promise<ChatSendResult> => {
      const { data, status } = await sendChat(courseId, message);
      if (data) {
        return {
          ok: true,
          content: data.reply_md,
          citations: data.citations.map((citation) => ({
            n: citation.n,
            sectionId: citation.section_id,
            page: citation.page,
            sourceRef: citation.source_ref,
          })),
        };
      }
      return { ok: false, ...describeSendError(status) };
    },
    [courseId],
  );

  const handleCitationClick = useCallback(
    (citation: ChatCitation) => {
      router.push(`/course/${courseId}?section=${citation.sectionId}`);
      onClose();
    },
    [courseId, router, onClose],
  );

  if (!open) return null;

  return (
    <div
      role="complementary"
      aria-label="Course chat"
      className="flex w-96 shrink-0 flex-col border-l border-border"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Chat</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chat"
          className="rounded-md border border-border px-2 py-1 text-sm"
        >
          Close
        </button>
      </div>
      <Chat loadHistory={loadHistory} sendFn={sendFn} onCitationClick={handleCitationClick} />
    </div>
  );
}
