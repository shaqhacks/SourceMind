import Link from "next/link";

import DueBadge from "@/components/DueBadge";

/**
 * App header: a home link back to the dashboard plus the due-review badge.
 * Extracted out of app/layout.tsx so it's unit-testable on its own — RTL
 * can't cleanly mount RootLayout's own <html>/<head>/next/font wrapper, the
 * same reason SkipToMainLink lives in its own file.
 */
export default function SiteHeader() {
  return (
    <header className="flex items-center justify-between border-b border-black/10 px-6 py-4 dark:border-white/10">
      <h1 className="text-lg font-semibold">
        <Link href="/">SourceMind</Link>
      </h1>
      <DueBadge />
    </header>
  );
}
