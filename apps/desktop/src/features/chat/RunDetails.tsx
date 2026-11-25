import { useState } from "react";
import { ToolSteps } from "./ToolSteps";
import { useRun, type Run, type ToolCall } from "./api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorMessage } from "@/lib/tauri";

const STATUS: Record<Run["status"], string> = {
  queued: "Waiting to start",
  running: "Working",
  waiting_approval: "Waiting for your approval",
  paused: "Paused",
  completed: "Finished",
  failed: "Failed",
  cancelled: "Stopped",
  needs_review: "Needs review",
};

const STOP_REASON: Record<string, string> = {
  step_limit: "Stopped at the step limit",
  run_token_limit: "Stopped at the token limit for one request",
  daily_token_limit: "Stopped at your daily token limit",
  output_limit: "The reply reached the length limit",
};

function duration(run: Run): string {
  if (!run.started_at || !run.finished_at) return "-";
  const total = Math.max(0, Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000;
  return total < 60
    ? `${total.toFixed(1)}s`
    : `${Math.floor(total / 60)}m ${Math.round(total % 60)}s`;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}

/** A small "Details" link under a reply that opens the run: steps, tools, tokens, time. */
export function RunDetails({ runId, steps }: { runId: string; steps: ToolCall[] }) {
  const [open, setOpen] = useState(false);
  const run = useRun(runId, open);

  return (
    <>
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground block text-[11px] underline-offset-2 hover:underline"
        onClick={() => setOpen(true)}
      >
        Details
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Run details</DialogTitle>
            <DialogDescription>What the Bot did for this reply.</DialogDescription>
          </DialogHeader>
          {run.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
          {run.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(run.error, "Could not load this run.")}
            </p>
          )}
          {run.isSuccess && (
            <div className="space-y-4 text-sm">
              <dl className="space-y-1">
                <Row
                  label="Status"
                  value={(run.data.error && STOP_REASON[run.data.error]) ?? STATUS[run.data.status]}
                />
                <Row label="Steps" value={String(run.data.steps)} />
                <Row label="Tools used" value={String(steps.length)} />
                <Row
                  label="Tokens"
                  value={`${run.data.input_tokens.toLocaleString()} in, ${run.data.output_tokens.toLocaleString()} out`}
                />
                <Row label="Duration" value={duration(run.data)} />
              </dl>
              {run.data.status === "failed" && run.data.error && (
                <p className="text-destructive text-xs">{run.data.error}</p>
              )}
              {steps.length > 0 ? (
                <ToolSteps steps={steps} />
              ) : (
                <p className="text-muted-foreground text-xs">No tools were used.</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
