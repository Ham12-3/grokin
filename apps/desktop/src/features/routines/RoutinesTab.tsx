import { useState, type FormEvent } from "react";
import {
  describeTrigger,
  formatWhen,
  useCronPreview,
  useRoutineActions,
  useRoutineRuns,
  useRoutines,
  type Routine,
  type RoutineInput,
  type Trigger,
} from "./api";
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
import type { Bot } from "@/features/bots/api";
import { ToolSteps } from "@/features/chat/ToolSteps";
import { useSkills } from "@/features/skills/api";
import { errorMessage } from "@/lib/tauri";

const STATUS: Record<string, string> = {
  queued: "Starting",
  running: "Running",
  paused: "Paused",
  waiting_approval: "Needs your approval",
  needs_review: "Needs your approval",
  completed: "Done",
  failed: "Failed",
  cancelled: "Stopped",
};

const SELECT =
  "border-input bg-background h-9 w-full rounded-md border px-2 text-sm focus-visible:outline-2";

type Preset = "daily" | "weekdays" | "hourly" | "custom" | "webhook";

function buildTrigger(preset: Preset, time: string, cron: string, timezone: string): Trigger {
  if (preset === "webhook") return { type: "webhook" };
  const [hour, minute] = time.split(":").map((part) => String(Number(part)));
  const expression =
    preset === "daily"
      ? `${minute} ${hour} * * *`
      : preset === "weekdays"
        ? `${minute} ${hour} * * 1-5`
        : preset === "hourly"
          ? "0 * * * *"
          : cron.trim();
  return { type: "cron", cron: expression, timezone };
}

interface NewRoutineProps {
  bot: Bot;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: RoutineInput) => void;
}

function NewRoutineDialog({ bot, busy, error, onClose, onSubmit }: NewRoutineProps) {
  const skills = useSkills(bot.id);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [skillId, setSkillId] = useState("");
  const [preset, setPreset] = useState<Preset>("daily");
  const [time, setTime] = useState("09:00");
  const [cron, setCron] = useState("0 9 * * 1");
  const [notify, setNotify] = useState(true);

  const chosen = skillId || skills.data?.[0]?.id || "";
  const trigger = buildTrigger(preset, time, cron, timezone);
  const scheduled = trigger.type === "cron";
  const preview = useCronPreview(scheduled ? trigger.cron : "", timezone, scheduled);
  const valid = Boolean(chosen) && (!scheduled || preview.isSuccess);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) onSubmit({ skill_id: chosen, trigger, notify });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New routine</DialogTitle>
          <DialogDescription>
            {bot.name} runs a skill by itself, even when Crew is closed.
          </DialogDescription>
        </DialogHeader>
        {skills.isSuccess && skills.data.length === 0 ? (
          <p className="text-sm">A routine runs a skill. Create a skill in the Skills tab first.</p>
        ) : (
          <form className="space-y-3" onSubmit={submit}>
            <div className="space-y-1">
              <Label htmlFor="routine-skill">Skill</Label>
              <select
                id="routine-skill"
                className={SELECT}
                value={chosen}
                onChange={(event) => setSkillId(event.target.value)}
              >
                {skills.data?.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="routine-when">When</Label>
              <select
                id="routine-when"
                className={SELECT}
                value={preset}
                onChange={(event) => setPreset(event.target.value as Preset)}
              >
                <option value="daily">Every day at</option>
                <option value="weekdays">Every weekday at</option>
                <option value="hourly">Every hour</option>
                <option value="custom">Custom schedule (cron)</option>
                <option value="webhook">When a webhook is called</option>
              </select>
            </div>
            {(preset === "daily" || preset === "weekdays") && (
              <div className="space-y-1">
                <Label htmlFor="routine-time">Time ({timezone})</Label>
                <Input
                  id="routine-time"
                  type="time"
                  required
                  value={time}
                  onChange={(event) => setTime(event.target.value)}
                />
              </div>
            )}
            {preset === "custom" && (
              <div className="space-y-1">
                <Label htmlFor="routine-cron">Schedule: minute hour day month weekday</Label>
                <Input
                  id="routine-cron"
                  className="font-mono"
                  value={cron}
                  onChange={(event) => setCron(event.target.value)}
                />
              </div>
            )}
            {scheduled && (
              <p className="text-muted-foreground text-xs" role="status">
                {preview.isSuccess &&
                  `${describeTrigger(trigger)}. Next: ${preview.data.next_runs
                    .map((run) => formatWhen(run))
                    .join(", ")}`}
                {preview.isError && errorMessage(preview.error, "That schedule is not valid.")}
                {preview.isPending && "Checking the schedule..."}
              </p>
            )}
            {preset === "webhook" && (
              <p className="text-muted-foreground text-xs">
                You get a secret web address after saving. It is shown once.
              </p>
            )}
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={notify}
                onChange={(event) => setNotify(event.target.checked)}
              />
              Notify me when it finishes
            </label>
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
                Create routine
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function History({ routine }: { routine: Routine }) {
  const runs = useRoutineRuns(routine.id, true);
  if (runs.isPending) return <p className="text-muted-foreground text-xs">Loading...</p>;
  if (runs.isError) {
    return (
      <p role="alert" className="text-destructive text-xs">
        {errorMessage(runs.error, "Could not load the history.")}
      </p>
    );
  }
  if (runs.data.length === 0) {
    return <p className="text-muted-foreground text-xs">It has not run yet.</p>;
  }
  return (
    <ul aria-label={`History of ${routine.skill_name}`} className="space-y-1">
      {runs.data.map((run) => (
        <li key={run.run_id}>
          <details className="text-xs">
            <summary className="cursor-pointer">
              {formatWhen(run.created_at)}: {STATUS[run.status] ?? run.status}
              {run.source !== "schedule" && ` (${run.source})`}
            </summary>
            <div className="border-border mt-1 ml-1.5 space-y-1 border-l pl-3">
              {run.tool_calls.length > 0 && <ToolSteps steps={run.tool_calls} />}
              {run.reply && <p className="break-words whitespace-pre-wrap">{run.reply}</p>}
              {run.error && <p className="text-destructive">{run.error}</p>}
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
}

/** Skills this Bot runs by itself: on a schedule or from a webhook. */
export function RoutinesTab({ bot }: { bot: Bot }) {
  const routines = useRoutines(bot.id);
  const { create, setPaused, test, remove } = useRoutineActions(bot.id);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const failed = setPaused.error ?? test.error ?? remove.error;

  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-xs">They run even when Crew is closed.</p>
        <Button size="sm" onClick={() => setCreating(true)}>
          New routine
        </Button>
      </div>
      {webhookUrl && (
        <div role="status" className="border-border space-y-1 rounded-md border p-2 text-xs">
          <p className="font-medium">Webhook address (shown once, keep it secret)</p>
          <code className="block break-all">{webhookUrl}</code>
          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void navigator.clipboard?.writeText(webhookUrl)}
            >
              Copy
            </Button>
            <Button size="sm" variant="outline" onClick={() => setWebhookUrl(null)}>
              Done
            </Button>
          </div>
        </div>
      )}
      {routines.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
      {routines.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(routines.error, "Could not load routines.")}
        </p>
      )}
      {routines.isSuccess && routines.data.length === 0 && (
        <p className="text-muted-foreground text-sm">No routines yet.</p>
      )}
      <ul aria-label="Routines" className="space-y-2">
        {routines.data?.map((routine) => (
          <li key={routine.id} className="border-border space-y-1 rounded-md border p-2">
            <p className="text-sm font-medium break-words">{routine.skill_name}</p>
            <p className="text-muted-foreground text-xs">
              {describeTrigger(routine.trigger)}
              {routine.paused
                ? " · Paused"
                : routine.next_run_at
                  ? ` · Next: ${formatWhen(routine.next_run_at)}`
                  : ""}
            </p>
            <p className="text-muted-foreground text-xs">
              {routine.last_run
                ? `Last: ${STATUS[routine.last_run.status] ?? routine.last_run.status}, ${formatWhen(routine.last_run.at)}`
                : "Has not run yet"}
            </p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button
                size="sm"
                variant="outline"
                aria-label={`${routine.paused ? "Resume" : "Pause"} ${routine.skill_name}`}
                disabled={setPaused.isPending}
                onClick={() => setPaused.mutate({ id: routine.id, paused: !routine.paused })}
              >
                {routine.paused ? "Resume" : "Pause"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                aria-label={`Run ${routine.skill_name} now`}
                disabled={test.isPending}
                onClick={() => test.mutate(routine.id)}
              >
                Run now
              </Button>
              <Button
                size="sm"
                variant="outline"
                aria-expanded={open === routine.id}
                aria-label={`History of ${routine.skill_name}`}
                onClick={() => setOpen(open === routine.id ? null : routine.id)}
              >
                History
              </Button>
              <Button
                size="sm"
                variant="outline"
                aria-label={`Delete ${routine.skill_name}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(routine.id)}
              >
                Delete
              </Button>
            </div>
            {open === routine.id && <History routine={routine} />}
          </li>
        ))}
      </ul>
      {failed && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(failed)}
        </p>
      )}
      {creating && (
        <NewRoutineDialog
          bot={bot}
          busy={create.isPending}
          error={create.isError ? errorMessage(create.error) : null}
          onClose={() => {
            create.reset();
            setCreating(false);
          }}
          onSubmit={(input) =>
            create.mutate(input, {
              onSuccess: (routine) => {
                setCreating(false);
                setWebhookUrl(routine.webhook_url ?? null);
              },
            })
          }
        />
      )}
    </div>
  );
}
