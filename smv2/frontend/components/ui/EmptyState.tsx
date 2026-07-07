import type { ReactNode } from "react";

export interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  cta?: ReactNode;
}

export default function EmptyState({ icon, title, body, cta }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-10 text-center">
      {icon ? (
        <span aria-hidden="true" className="text-3xl">
          {icon}
        </span>
      ) : null}
      <p className="text-lg font-medium">{title}</p>
      {body ? <p className="text-sm text-muted-foreground">{body}</p> : null}
      {cta ? <div className="mt-2">{cta}</div> : null}
    </div>
  );
}
