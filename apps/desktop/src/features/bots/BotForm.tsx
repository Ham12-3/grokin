import { useState, type FormEvent, type ReactNode } from "react";
import type { ApprovalMode, BotInput } from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const AVATARS = [
  "🤖", "📬", "🔎", "📝", "📊", "📅", "💬", "🧭",
  "🛠️", "🎯", "📣", "💡", "🧾", "🗂️", "🌐", "⭐",
]; // prettier-ignore

const APPROVAL_MODES: { value: ApprovalMode; label: string; help: string }[] = [
  { value: "always_ask", label: "Always ask", help: "Asks before every action." },
  {
    value: "ask_risky",
    label: "Ask for risky actions",
    help: "Asks before sending, posting, buying, deleting or sharing.",
  },
  {
    value: "never_ask",
    label: "Never ask",
    help: "Works on its own. Risky actions still always ask.",
  },
];

interface BotFormProps {
  initial?: BotInput;
  submitLabel: string;
  busy: boolean;
  error?: string | null;
  onSubmit: (bot: BotInput) => void;
  extraActions?: ReactNode;
}

const EMPTY: BotInput = {
  name: "",
  avatar: AVATARS[0],
  job: "",
  instructions: "",
  approval_mode: "ask_risky",
};

export function BotForm({
  initial,
  submitLabel,
  busy,
  error,
  onSubmit,
  extraActions,
}: BotFormProps) {
  const [bot, setBot] = useState<BotInput>({ ...EMPTY, ...initial });
  const set = (patch: Partial<BotInput>) => setBot((current) => ({ ...current, ...patch }));
  const valid = bot.name.trim().length > 0 && bot.job.trim().length > 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) onSubmit({ ...bot, name: bot.name.trim(), job: bot.job.trim() });
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="bot-name">Name</Label>
        <Input
          id="bot-name"
          value={bot.name}
          maxLength={60}
          placeholder="Inbox Bot"
          onChange={(event) => set({ name: event.target.value })}
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Avatar</legend>
        <div className="grid grid-cols-8 gap-1">
          {AVATARS.map((avatar) => (
            <button
              key={avatar}
              type="button"
              aria-label={`Avatar ${avatar}`}
              aria-pressed={bot.avatar === avatar}
              onClick={() => set({ avatar })}
              className={cn(
                "hover:bg-muted flex h-9 items-center justify-center rounded-md text-lg",
                bot.avatar === avatar && "bg-muted ring-ring ring-2",
              )}
            >
              {avatar}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="space-y-2">
        <Label htmlFor="bot-job">Job</Label>
        <Input
          id="bot-job"
          value={bot.job}
          maxLength={200}
          placeholder="One line: what this Bot does for you"
          onChange={(event) => set({ job: event.target.value })}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="bot-instructions">Instructions</Label>
        <Textarea
          id="bot-instructions"
          value={bot.instructions ?? ""}
          maxLength={8000}
          rows={4}
          placeholder="How it should work, tone, things to avoid (optional)"
          onChange={(event) => set({ instructions: event.target.value })}
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Approvals</legend>
        {APPROVAL_MODES.map((mode) => (
          <label key={mode.value} className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="radio"
              name="approval-mode"
              className="mt-1"
              checked={bot.approval_mode === mode.value}
              onChange={() => set({ approval_mode: mode.value })}
            />
            <span>
              <span className="font-medium">{mode.label}</span>
              <span className="text-muted-foreground block text-xs">{mode.help}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}

      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-2">{extraActions}</div>
        <Button type="submit" disabled={busy || !valid}>
          {busy ? "Saving..." : submitLabel}
        </Button>
      </div>
    </form>
  );
}
