import { Check, Pencil, Trash2, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useMemory, useMemoryActions, type MemoryLine } from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Bot } from "@/features/bots/api";
import { errorMessage } from "@/lib/tauri";

function Line({ line, botId }: { line: MemoryLine; botId: string }) {
  const { edit, remove } = useMemoryActions(botId);
  const [draft, setDraft] = useState<string | null>(null);

  if (draft !== null) {
    const save = (event: FormEvent) => {
      event.preventDefault();
      if (!draft.trim()) return;
      edit.mutate({ id: line.id, text: draft.trim() }, { onSuccess: () => setDraft(null) });
    };
    return (
      <li>
        <form className="flex items-center gap-1" onSubmit={save}>
          <Input
            aria-label="Memory line"
            autoFocus
            maxLength={300}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button
            type="submit"
            size="icon"
            variant="ghost"
            aria-label="Save line"
            disabled={edit.isPending}
          >
            <Check />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label="Cancel"
            onClick={() => setDraft(null)}
          >
            <X />
          </Button>
        </form>
      </li>
    );
  }
  return (
    <li className="group flex items-start gap-1 text-sm">
      <p className="min-w-0 flex-1 py-1.5 break-words">{line.text}</p>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Edit: ${line.text}`}
        onClick={() => setDraft(line.text)}
      >
        <Pencil />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Delete: ${line.text}`}
        disabled={remove.isPending}
        onClick={() => remove.mutate(line.id)}
      >
        <Trash2 />
      </Button>
    </li>
  );
}

/** What this Bot remembers about the user. Every line can be changed or deleted. */
export function MemoryTab({ bot }: { bot: Bot }) {
  const memory = useMemory(bot.id);
  const { add } = useMemoryActions(bot.id);
  const [text, setText] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    add.mutate(text.trim(), { onSuccess: () => setText("") });
  }

  return (
    <div className="space-y-3 pt-2">
      <p className="text-muted-foreground text-xs">
        {bot.name} follows these in every chat. It adds lines when you tell it something lasting.
      </p>
      {memory.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
      {memory.isError && (
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(memory.error, "Could not load memory.")}
        </p>
      )}
      {memory.isSuccess && memory.data.length === 0 && (
        <p className="text-muted-foreground text-sm">Nothing remembered yet.</p>
      )}
      <ul aria-label="Memory" className="space-y-1">
        {memory.data?.map((line) => (
          <Line key={line.id} line={line} botId={bot.id} />
        ))}
      </ul>
      <form className="flex gap-2" onSubmit={submit}>
        <Input
          aria-label="New memory line"
          placeholder="Add a line, for example: I prefer short answers"
          maxLength={300}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="submit" size="sm" disabled={add.isPending || !text.trim()}>
          Add line
        </Button>
      </form>
      {add.isError && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(add.error)}
        </p>
      )}
    </div>
  );
}
