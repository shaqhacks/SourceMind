"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiResult, GradeCardOut, ReviewQueueCardOut } from "@/lib/api/client";
import {
  formatIntervalPreview,
  previewIntervalDays,
  type ReviewGrade,
} from "@/lib/review/intervalPreview";
import { gradeCardAndNotify } from "@/lib/review/gradeCardAndNotify";

const GRADE_LABELS: Record<ReviewGrade, string> = {
  1: "Again",
  2: "Hard",
  3: "Good",
  4: "Easy",
};

const GRADE_BUTTON_BG: Record<ReviewGrade, string> = {
  1: "bg-accent-200",
  2: "bg-accent-100",
  3: "bg-sage-200",
  4: "bg-sage-300",
};

const GRADES: ReviewGrade[] = [1, 2, 3, 4];

export interface ReviewGradeRequest {
  grade: ReviewGrade;
  token: number;
}

interface ReviewGradeControlsProps {
  card: ReviewQueueCardOut;
  onGraded?: (grade: ReviewGrade, result: ApiResult<GradeCardOut>) => void;
  onPendingChange?: (pending: boolean) => void;
  request?: ReviewGradeRequest | null;
  className?: string;
}

export default function ReviewGradeControls({
  card,
  onGraded,
  onPendingChange,
  request,
  className = "",
}: ReviewGradeControlsProps) {
  const shownAtRef = useRef<number | null>(null);
  const handledRequestTokenRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  const [submission, setSubmission] = useState<{
    cardId: string;
    pendingGrade: ReviewGrade | null;
    savedGrade: ReviewGrade | null;
    error: string | null;
  }>({
    cardId: card.id,
    pendingGrade: null,
    savedGrade: null,
    error: null,
  });

  const pendingGrade = submission.cardId === card.id ? submission.pendingGrade : null;
  const savedGrade = submission.cardId === card.id ? submission.savedGrade : null;
  const error = submission.cardId === card.id ? submission.error : null;

  const submitGrade = useCallback(
    async (grade: ReviewGrade) => {
      if (inFlightRef.current || pendingGrade !== null || savedGrade !== null) return;

      inFlightRef.current = true;
      setSubmission({ cardId: card.id, pendingGrade: grade, savedGrade: null, error: null });
      onPendingChange?.(true);
      const elapsedMs = Date.now() - (shownAtRef.current ?? Date.now());
      const result = await gradeCardAndNotify(card.id, grade, elapsedMs);
      onPendingChange?.(false);
      if (result.ok) {
        setSubmission({ cardId: card.id, pendingGrade: null, savedGrade: grade, error: null });
        onGraded?.(grade, result);
      } else {
        inFlightRef.current = false;
        setSubmission({
          cardId: card.id,
          pendingGrade: null,
          savedGrade: null,
          error: "Could not save this grade. Try again.",
        });
      }
    },
    [card.id, onGraded, onPendingChange, pendingGrade, savedGrade],
  );

  useEffect(() => {
    shownAtRef.current = Date.now();
    handledRequestTokenRef.current = null;
    inFlightRef.current = false;
  }, [card.id]);

  useEffect(() => {
    if (!request || handledRequestTokenRef.current === request.token) return;
    handledRequestTokenRef.current = request.token;
    void submitGrade(request.grade);
  }, [request, submitGrade]);

  const locked = pendingGrade !== null || savedGrade !== null;

  return (
    <div className={className}>
      <div role="group" aria-label="Grade flashcard" className="grid grid-cols-4 gap-3">
        {GRADES.map((grade) => {
          const preview = formatIntervalPreview(
            previewIntervalDays(grade, {
              intervalDays: card.interval_days,
              ease: card.ease,
              reps: card.reps,
            }),
          );
          return (
            <button
              key={grade}
              type="button"
              disabled={locked}
              onClick={() => void submitGrade(grade)}
              aria-label={`${GRADE_LABELS[grade]} (${grade}) ${preview}`}
              className={`flex flex-col items-center gap-1 rounded-md py-3 text-foreground transition-opacity hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-65 ${GRADE_BUTTON_BG[grade]}`}
            >
              <span aria-hidden="true" className="text-[15px] font-semibold">
                {GRADE_LABELS[grade]}
              </span>
              <span aria-hidden="true" className="font-mono text-[11px] opacity-70">
                {grade} · {preview}
              </span>
            </button>
          );
        })}
      </div>
      {error && (
        <p role="alert" className="mt-3 text-center text-sm text-accent-800">
          {error}
        </p>
      )}
      {savedGrade && (
        <p role="status" className="mt-3 text-center text-sm text-muted-foreground">
          Saved as {GRADE_LABELS[savedGrade]}.
        </p>
      )}
    </div>
  );
}
