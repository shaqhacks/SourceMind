"use client";

import { useEffect, useState } from "react";

import { getLlmUsage, type LlmUsageOut } from "@/lib/api/client";

export interface UsageFooterProps {
  courseId: string;
}

/**
 * Small footer line surfacing spend so far. The parent remounts this
 * (via `key`) whenever a lesson generation settles, since that's the only
 * time the numbers actually change — no polling.
 */
export default function UsageFooter({ courseId }: UsageFooterProps) {
  const [usage, setUsage] = useState<LlmUsageOut | null>(null);

  useEffect(() => {
    let active = true;
    getLlmUsage(courseId).then(({ data }) => {
      if (active && data) setUsage(data);
    });
    return () => {
      active = false;
    };
  }, [courseId]);

  if (!usage) return null;

  return (
    <p className="border-t border-divider px-5 py-1.5 text-xs text-muted-foreground">
      LLM usage: {usage.calls} call{usage.calls === 1 ? "" : "s"} · ${usage.est_cost_usd.toFixed(2)}
    </p>
  );
}
