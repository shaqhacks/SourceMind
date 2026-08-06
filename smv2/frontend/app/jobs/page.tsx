import { Suspense } from "react";

import JobsClient from "@/components/jobs/JobsClient";

export default function JobsPage() {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-8 text-sm text-muted-foreground">
          Loading...
        </p>
      }
    >
      <JobsClient />
    </Suspense>
  );
}
