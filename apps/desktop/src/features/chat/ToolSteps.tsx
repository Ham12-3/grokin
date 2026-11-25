import { Check, CircleSlash, LoaderCircle, TriangleAlert } from "lucide-react";
import type { ToolCall } from "./api";

function seconds(call: ToolCall): string | null {
  if (!call.started_at || !call.finished_at) return null;
  const ms = Date.parse(call.finished_at) - Date.parse(call.started_at);
  return `${Math.max(0, ms / 1000).toFixed(1)}s`;
}

const STATUS_LABEL: Record<ToolCall["status"], string> = {
  pending: "Starting",
  running: "Running",
  waiting_approval: "Waiting for approval",
  ok: "Done",
  error: "Failed",
  rejected: "Not run",
};

function StatusIcon({ status }: { status: ToolCall["status"] }) {
  const className = "size-3.5 shrink-0";
  if (status === "ok") return <Check className={`${className} text-emerald-600`} />;
  if (status === "error") return <TriangleAlert className={`${className} text-destructive`} />;
  if (status === "rejected" || status === "waiting_approval") {
    return <CircleSlash className={`${className} text-amber-600`} />;
  }
  return <LoaderCircle className={`${className} animate-spin`} />;
}

/**
 * What the Bot did, one row per tool call. Collapsed by default. Only safe summaries are
 * shown: the server never sends raw tool arguments.
 */
export function ToolSteps({ steps }: { steps: ToolCall[] }) {
  return (
    <ul aria-label="Steps" className="space-y-1">
      {steps.map((step) => (
        <li key={step.id}>
          <details className="group text-xs">
            <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-1.5">
              <StatusIcon status={step.status} />
              <span className="truncate">{step.summary}</span>
            </summary>
            <dl className="border-border text-muted-foreground mt-1 ml-1.5 space-y-0.5 border-l pl-3">
              <div>
                <dt className="inline font-medium">Tool: </dt>
                <dd className="inline">{step.tool}</dd>
              </div>
              <div>
                <dt className="inline font-medium">Status: </dt>
                <dd className="inline">
                  {STATUS_LABEL[step.status]}
                  {seconds(step) ? ` in ${seconds(step)}` : ""}
                </dd>
              </div>
              {step.result_summary && (
                <div>
                  <dt className="inline font-medium">Result: </dt>
                  <dd className="inline break-words">{step.result_summary}</dd>
                </div>
              )}
            </dl>
          </details>
        </li>
      ))}
    </ul>
  );
}
