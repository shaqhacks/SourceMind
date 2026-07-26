import { Suspense } from "react";

import TestsPageClient from "@/components/tests/TestsPageClient";

export const metadata = { title: "Tests — SourceMind" };

// /tests has no dynamic route segment, so Next.js tries to statically
// prerender it at build time — useSearchParams() (used for ?course=, same
// pattern as /review) requires a Suspense boundary in that case.
export default function TestsPage() {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-8 text-sm text-muted-foreground">
          Loading…
        </p>
      }
    >
      <TestsPageClient />
    </Suspense>
  );
}
