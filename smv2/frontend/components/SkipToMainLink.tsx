/** First tabbable element in the document — visually hidden until it
 * receives keyboard focus, then jumps straight to <main id="main-content">
 * (which needs tabIndex={-1} for the fragment navigation to actually move
 * focus there, not just scroll to it). */
export default function SkipToMainLink() {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-border focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground"
    >
      Skip to main content
    </a>
  );
}
