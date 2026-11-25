import { useState, type FormEvent } from "react";
import type { Approval, ApprovalArgs } from "./api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/** Fields the user edits one by one. Other kinds are edited as JSON. */
const FORMS: Partial<
  Record<Approval["preview"]["kind"], { name: string; label: string; long?: boolean }[]>
> = {
  email: [
    { name: "to", label: "To" },
    { name: "subject", label: "Subject" },
    { name: "body", label: "Message", long: true },
  ],
  post: [{ name: "text", label: "Post", long: true }],
};

interface EditApprovalDialogProps {
  approval: Approval;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onApprove: (args: ApprovalArgs) => void;
}

/** Change what the Bot drafted, then approve it. The server checks the result again. */
export function EditApprovalDialog({
  approval,
  busy,
  error,
  onClose,
  onApprove,
}: EditApprovalDialogProps) {
  const { kind, fields } = approval.preview;
  const form = FORMS[kind];
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((form ?? []).map((field) => [field.name, String(fields[field.name] ?? "")])),
  );
  const [json, setJson] = useState(() => JSON.stringify(fields, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (form) {
      onApprove({ ...fields, ...values });
      return;
    }
    try {
      const parsed: unknown = JSON.parse(json);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("not an object");
      }
      setJsonError(null);
      onApprove(parsed as ApprovalArgs);
    } catch {
      setJsonError("This is not valid JSON. Fix it and try again.");
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit before approving</DialogTitle>
          <DialogDescription>{approval.title}</DialogDescription>
        </DialogHeader>
        <form className="space-y-3" onSubmit={submit}>
          {form?.map((field) => (
            <div key={field.name} className="space-y-1">
              <Label htmlFor={`approval-${field.name}`}>{field.label}</Label>
              {field.long ? (
                <Textarea
                  id={`approval-${field.name}`}
                  rows={6}
                  value={values[field.name]}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field.name]: event.target.value }))
                  }
                />
              ) : (
                <Input
                  id={`approval-${field.name}`}
                  value={values[field.name]}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field.name]: event.target.value }))
                  }
                />
              )}
            </div>
          ))}
          {!form && (
            <div className="space-y-1">
              <Label htmlFor="approval-json">Details</Label>
              <Textarea
                id="approval-json"
                rows={8}
                className="font-mono text-xs"
                value={json}
                onChange={(event) => setJson(event.target.value)}
              />
            </div>
          )}
          {(jsonError ?? error) && (
            <p role="alert" className="text-destructive text-xs">
              {jsonError ?? error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              Approve with changes
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
