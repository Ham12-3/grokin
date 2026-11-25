import { cn } from "@/lib/utils";

/** Idle, working, or waiting for the user's approval. */
export function StatusDot({ working, waiting = false }: { working: boolean; waiting?: boolean }) {
  const label = waiting ? "Waiting for you" : working ? "Working" : "Idle";
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        waiting
          ? "bg-amber-500"
          : working
            ? "animate-pulse bg-emerald-500"
            : "bg-muted-foreground/40",
      )}
    />
  );
}
