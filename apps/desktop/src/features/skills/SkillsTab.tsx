import { useState, type FormEvent } from "react";
import { useSkillActions, useSkills, type Skill, type SkillInput } from "./api";
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
import type { Bot } from "@/features/bots/api";
import { errorMessage } from "@/lib/tauri";

const EMPTY: SkillInput = { name: "", description: "", steps: "", rules: "" };

interface SkillFormProps {
  initial: SkillInput;
  title: string;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: SkillInput) => void;
}

function SkillForm({ initial, title, busy, error, onClose, onSubmit }: SkillFormProps) {
  const [values, setValues] = useState(initial);
  const set = (name: keyof SkillInput) => (event: { target: { value: string } }) =>
    setValues((current) => ({ ...current, [name]: event.target.value }));
  const valid = values.name.trim().length > 0 && values.steps.trim().length > 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) onSubmit(values);
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            A procedure this Bot can run again from the chat with /.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-3" onSubmit={submit}>
          <div className="space-y-1">
            <Label htmlFor="skill-name">Name</Label>
            <Input id="skill-name" maxLength={80} value={values.name} onChange={set("name")} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="skill-description">What it does (one line)</Label>
            <Input
              id="skill-description"
              maxLength={300}
              value={values.description ?? ""}
              onChange={set("description")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="skill-steps">Steps (markdown)</Label>
            <Textarea
              id="skill-steps"
              rows={8}
              className="font-mono text-xs"
              placeholder={"1. Open ...\n2. Read ...\n3. Write a summary to ..."}
              value={values.steps}
              onChange={set("steps")}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="skill-rules">Rules (optional)</Label>
            <Textarea
              id="skill-rules"
              rows={3}
              value={values.rules ?? ""}
              onChange={set("rules")}
            />
          </div>
          {error && (
            <p role="alert" className="text-destructive text-xs">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !valid}>
              Save skill
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface SkillsTabProps {
  bot: Bot;
  /** False while the Bot is busy: a skill cannot start then. */
  canRun: boolean;
  onRun: (skill: Skill) => void;
}

/** This Bot's saved procedures: create, edit, delete, run now. */
export function SkillsTab({ bot, canRun, onRun }: SkillsTabProps) {
  const skills = useSkills(bot.id);
  const { create, update, remove } = useSkillActions(bot.id);
  const [editing, setEditing] = useState<Skill | "new" | null>(null);
  const saving = editing === "new" ? create : update;

  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-xs">Type / in the chat to run one.</p>
        <Button size="sm" onClick={() => setEditing("new")}>
          New skill
        </Button>
      </div>
      {skills.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
      {skills.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(skills.error, "Could not load skills.")}
        </p>
      )}
      {skills.isSuccess && skills.data.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No skills yet. After a task, ask {bot.name} to &quot;save that as a skill&quot;.
        </p>
      )}
      <ul aria-label="Skills" className="space-y-2">
        {skills.data?.map((skill) => (
          <li key={skill.id} className="border-border space-y-1 rounded-md border p-2">
            <p className="text-sm font-medium break-words">
              {skill.name} <span className="text-muted-foreground font-normal">/{skill.slug}</span>
            </p>
            {skill.description && (
              <p className="text-muted-foreground text-xs break-words">{skill.description}</p>
            )}
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button
                size="sm"
                disabled={!canRun}
                aria-label={`Run ${skill.name} now`}
                onClick={() => onRun(skill)}
              >
                Run now
              </Button>
              <Button
                size="sm"
                variant="outline"
                aria-label={`Edit ${skill.name}`}
                onClick={() => setEditing(skill)}
              >
                Edit
              </Button>
              <Button
                size="sm"
                variant="outline"
                aria-label={`Delete ${skill.name}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(skill.id)}
              >
                Delete
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {editing && (
        <SkillForm
          title={editing === "new" ? "New skill" : "Edit skill"}
          initial={
            editing === "new"
              ? EMPTY
              : {
                  name: editing.name,
                  description: editing.description,
                  steps: editing.steps,
                  rules: editing.rules,
                }
          }
          busy={saving.isPending}
          error={saving.isError ? errorMessage(saving.error) : null}
          onClose={() => {
            saving.reset();
            setEditing(null);
          }}
          onSubmit={(input) => {
            const done = { onSuccess: () => setEditing(null) };
            if (editing === "new") create.mutate(input, done);
            else update.mutate({ id: editing.id, input }, done);
          }}
        />
      )}
    </div>
  );
}
