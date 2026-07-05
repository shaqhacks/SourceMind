"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { getReviewSummary } from "@/lib/api/client";
import { subscribeReviewSettled } from "@/lib/review/reviewBus";

/**
 * Nav due-total badge. No polling — refetches only on route change (a
 * new page might have just settled something) and whenever the review
 * bus fires (a grade or a lesson/cards/test generation completed
 * somewhere in the tree).
 */
export default function DueBadge() {
  const pathname = usePathname();
  const [dueTotal, setDueTotal] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    getReviewSummary().then(({ data }) => {
      if (active && data) setDueTotal(data.due_total);
    });
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    let active = true;
    const unsubscribe = subscribeReviewSettled(() => {
      getReviewSummary().then(({ data }) => {
        if (active && data) setDueTotal(data.due_total);
      });
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  // A stable, always-mounted live region (rather than conditionally
  // mounting/unmounting the whole badge) is what lets a screen reader
  // reliably announce the count changing — e.g. right after a grade
  // settles the review bus and this refetches.
  return (
    <div aria-live="polite" aria-atomic="true">
      {dueTotal ? (
        <Link
          href="/review"
          className="rounded-full bg-accent px-2.5 py-1 text-xs font-medium text-white"
        >
          {dueTotal} due
        </Link>
      ) : null}
    </div>
  );
}
