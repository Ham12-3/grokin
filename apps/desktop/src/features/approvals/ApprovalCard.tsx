import { useState } from "react";
import { EditApprovalDialog } from "./EditApprovalDialog";
import { useAnswerApproval, type Approval } from "./api";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/tauri";

const text = (value: unknown): string =>
  typeof value === "string" ? value : value === undefined ? "" : JSON.stringify(value);

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground w-16 shrink-0">{label}</dt>
      <dd className="min-w-0 flex-1 break-words whitespace-pre-wrap">{value}</dd>
    </div>
  );
}

/** What the Bot wants to do, shown the way the user thinks about it. */
function Preview({ approval }: { approval: Approval }) {
  const { kind, fields, context } = approval.preview;
  if (kind === "email") {
    return (
      <dl className="space-y-1 text-sm">
        <Row label="To" value={text(fields.to)} />
        <Row label="Subject" value={text(fields.subject)} />
        <Row label="Message" value={text(fields.body)} />
      </dl>
    );
  }
  if (kind === "post") {
    return <p className="text-sm break-words whitespace-pre-wrap">{text(fields.text)}</p>;
  }
  if (kind === "purchase") {
    return (
      <dl className="space-y-1 text-sm">
        <Row label="Item" value={context?.item ?? "This page's form"} />
        <Row label="Page" value={context?.page ?? ""} />
      </dl>
    );
  }
  return (
    <div className="space-y-1 text-sm">
      {context?.page && <p className="text-muted-foreground break-all">{context.page}</p>}
      <pre className="bg-background max-h-40 overflow-auto rounded border p-2 text-xs">
        {JSON.stringify(fields, null, 2)}
      </pre>
    </div>
  );
}

interface ApprovalCardProps {
  approval: Approval;
  botName: string;
}

/** A risky action waiting for the user: Approve, Edit or Reject. Nothing runs until then. */
export function ApprovalCard({ approval, botName }: ApprovalCardProps) {
  const { approve, reject } = useAnswerApproval(approval.id);
  const [editing, setEditing] = useState(false);
  const busy = approve.isPending || reject.isPending;
  const failed = approve.error ?? reject.error;

  return (
    <article
      aria-label={`Approval: ${approval.title}`}
      className="border-border bg-muted/60 space-y-2 rounded-lg border px-3 py-2"
    >
      <header>
        <p className="text-muted-foreground text-xs">{botName} needs your approval</p>
        <h3 className="text-sm font-medium break-words">{approval.title}</h3>
      </header>
      <Preview approval={approval} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={() => approve.mutate(undefined)}>
          Approve
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(true)}>
          Edit
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => reject.mutate()}>
          Reject
        </Button>
      </div>
      {failed && !editing && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(failed)}
        </p>
      )}
      {editing && (
        <EditApprovalDialog
          approval={approval}
          busy={approve.isPending}
          error={approve.isError ? errorMessage(approve.error) : null}
          onClose={() => setEditing(false)}
          onApprove={(args) => approve.mutate(args, { onSuccess: () => setEditing(false) })}
        />
      )}
    </article>
  );
}
