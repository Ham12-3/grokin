import { cn } from "@/lib/utils";

/** Idle or working. "Waiting for you" arrives with approvals. */
export function StatusDot({ working }: { working: boolean }) {
  return (
    <span
      role="img"
      aria-label={working ? "Working" : "Idle"}
      title={working ? "Working" : "Idle"}
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        working ? "animate-pulse bg-emerald-500" : "bg-muted-foreground/40",
      )}
    />
  );
}
