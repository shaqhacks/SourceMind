"use client";

import { useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

import Chat, { type ChatCitation, type ChatSendResult, type ChatTurn } from "@/components/Chat";
import { recoveryAllowsRetry } from "@/components/RecoveryBanner";
import SelectionContextPill from "@/components/reader/SelectionContextPill";
import { getChatHistory, sendChat, type ChatSelectionIn, type ChatTurnOut } from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { useShellLayout } from "@/lib/hooks/useShellLayout";

export interface CourseChatDrawerProps {
  courseId: string;
  open: boolean;
  onClose: () => void;
  /** Set by CourseReader when "Add to chat" fires on a selected/highlighted
   * passage. Carried into the *next* sendChat call, then cleared via
   * onConsumeSelection so it attaches to exactly one turn. */
  pendingSelection?: ChatSelectionIn | null;
  /** Receives back the exact selection object that was actually sent (or
   * removed), so the parent can clear `pendingSelection` only if it's
   * still that same one. Without this, a selection attached *while* an
   * earlier send is in flight would get wiped out from under the user the
   * moment that earlier send's onConsumeSelection fires. */
  onConsumeSelection?: (sent: ChatSelectionIn) => void;
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

function describeSendError(
  status: number | undefined,
  error?: unknown,
): FetchError & { retryable: boolean } {
  const described = describeError(status, "The assistant", error);
  if (described.detail) {
    return {
      ...described,
      retryable: recoveryAllowsRetry(described.detail) && (status === undefined || status >= 500),
    };
  }
  if (status === 429) {
    return { message: "Assistant is busy — try again in a moment.", retryable: true };
  }
  if (status === 504) {
    return { message: "The assistant took too long to respond.", retryable: true };
  }
  if (status === undefined) {
    return { message: "Could not reach the assistant.", retryable: true };
  }
  return { ...described, retryable: status >= 500 };
}

/**
 * Course-chat wiring around the shared, API-agnostic Chat component:
 * translates send_chat/chat_history into Chat's props, and turns a
 * citation click into a reader navigation (using the structured
 * section_id field — source_ref is display-only and never parsed).
 */
export default function CourseChatDrawer({
  courseId,
  open,
  onClose,
  pendingSelection = null,
  onConsumeSelection,
}: CourseChatDrawerProps) {
  const router = useRouter();
  const layout = useShellLayout();
  const transientDrawer = layout !== "desktop";
  const shellRef = useRef<HTMLDivElement>(null);

  // Own scope while open, same pattern as ShortcutsOverlay: sits on top of
  // the reader's arrow/j/k/s/c scope so those don't fire behind an open
  // drawer. Maps "c" to onClose too (not just escape) — the topmost scope
  // shadows the reader's own "c" binding while this is open, so without
  // this, "c" would only ever open the drawer, never close it.
  useKeyboardShortcuts({ escape: onClose, c: onClose }, open);
  // Mobile/tablet drawers are modal because they cover the reading
  // column. Desktop chat stays a complementary docked panel.
  const drawerRef = useDialogFocus<HTMLDivElement>(open, { trap: transientDrawer });

  useEffect(() => {
    if (!open || !transientDrawer) return undefined;

    function handlePointerDown(event: PointerEvent) {
      if (shellRef.current && !shellRef.current.contains(event.target as Node)) {
        onClose();
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open, transientDrawer, onClose]);

  const loadHistory = useCallback(async () => {
    const { data } = await getChatHistory(courseId);
    if (!data) throw new Error("Failed to load chat history");
    return data.map(mapTurn);
  }, [courseId]);

  // Closes over `pendingSelection` rather than widening Chat's own sendFn
  // signature — Chat's history-loading effect keys on `loadHistory` only
  // (never `sendFn`), so this reference changing whenever pendingSelection
  // changes cannot retrigger the v1 transcript-reset bug documented on
  // Chat itself. No-selection path calls sendChat with exactly the same
  // two arguments as before (not a third explicit `undefined`), so that
  // behavior stays byte-identical.
  const sendFn = useCallback(
    async (message: string): Promise<ChatSendResult> => {
      const sentSelection = pendingSelection;
      const { data, status, error } = sentSelection
        ? await sendChat(courseId, message, sentSelection)
        : await sendChat(courseId, message);
      if (data) {
        // Attach the selection to exactly one turn: only consumed once the
        // send actually succeeds, so a failed/retryable send doesn't lose
        // it out from under a later retry. Passes the exact selection that
        // was sent (not just "clear whatever's pending now") so a *newer*
        // selection attached while this send was in flight survives.
        if (sentSelection) onConsumeSelection?.(sentSelection);
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
      const described = describeSendError(status, error);
      return {
        ok: false,
        message: described.message,
        retryable: described.retryable,
        errorDetail: described.detail,
      };
    },
    [courseId, pendingSelection, onConsumeSelection],
  );

  const handleCitationClick = useCallback(
    (citation: ChatCitation) => {
      router.push(`/course/${courseId}/read?section=${citation.sectionId}`);
      // Docked (wide viewport): the chat and reading column are
      // independent panels side by side, so there's no reason to lose
      // the conversation just to follow a citation — stay open, just
      // navigate. Narrow-viewport overlay: it covers the content, so
      // closing it is the only way to actually see the section just
      // navigated to.
      if (transientDrawer) onClose();
    },
    [courseId, router, onClose, transientDrawer],
  );

  if (!open) return null;

  const panel = (
    <div
      ref={drawerRef}
      role={transientDrawer ? "dialog" : "complementary"}
      aria-modal={transientDrawer ? "true" : undefined}
      aria-label="Course chat"
      tabIndex={-1}
      className={
        transientDrawer
          ? "fixed inset-y-0 right-0 z-40 flex w-96 max-w-[90vw] flex-col border-l border-divider bg-background shadow-lg"
          : "flex w-[340px] shrink-0 flex-col border-l border-divider"
      }
    >
      <div className="flex items-center justify-between gap-2 border-b border-divider px-4 py-3">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          Chat
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chat"
          className="rounded-md border border-border bg-surface-raised px-2.5 py-1 text-xs font-medium transition-colors hover:bg-foreground/[0.07]"
        >
          Close
        </button>
      </div>
      <Chat
        loadHistory={loadHistory}
        sendFn={sendFn}
        onCitationClick={handleCitationClick}
        composerAccessory={
          pendingSelection ? (
            <SelectionContextPill
              exact={pendingSelection.exact}
              onRemove={() => onConsumeSelection?.(pendingSelection)}
            />
          ) : null
        }
      />
    </div>
  );

  if (!transientDrawer) return panel;

  return (
    <div className="fixed inset-0 z-40 bg-foreground/25">
      <div ref={shellRef}>{panel}</div>
    </div>
  );
}
