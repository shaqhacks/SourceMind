/** animate-pulse is neutralized globally under prefers-reduced-motion (globals.css). */
export default function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-md bg-muted-foreground/15 ${className}`} />;
}
