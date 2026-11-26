import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileText } from "lucide-react";
import { useState } from "react";
import { upsertMessage, type Message } from "./api";
import { Button } from "@/components/ui/button";
import { answerSkillDraft, skillsKey } from "@/features/skills/api";
import { errorMessage } from "@/lib/tauri";

const str = (value: unknown): string => (typeof value === "string" ? value : "");

/** A skill the Bot drafted. It is saved only if the user clicks Save. */
function SkillDraftCard({ message }: { message: Message }) {
  const queryClient = useQueryClient();
  const card = message.card ?? {};
  const status = str(card.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function answer(action: "save" | "cancel") {
    setBusy(true);
    setError(null);
    try {
      upsertMessage(queryClient, await answerSkillDraft(message.chat_id, message.id, action));
      if (message.bot_id) {
        void queryClient.invalidateQueries({ queryKey: skillsKey(message.bot_id) });
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      aria-label={`Skill draft: ${str(card.name)}`}
      className="border-border bg-muted/60 mx-auto max-w-[75%] space-y-2 rounded-lg border px-3 py-2"
    >
      <header>
        <p className="text-muted-foreground text-xs">Skill draft</p>
        <h3 className="text-sm font-medium break-words">{str(card.name)}</h3>
        {str(card.description) && (
          <p className="text-muted-foreground text-xs break-words">{str(card.description)}</p>
        )}
      </header>
      <pre className="bg-background max-h-48 overflow-auto rounded border p-2 text-xs whitespace-pre-wrap">
        {str(card.steps)}
      </pre>
      {str(card.rules) && (
        <p className="text-xs break-words whitespace-pre-wrap">
          <span className="font-medium">Rules: </span>
          {str(card.rules)}
        </p>
      )}
      {status === "draft" && (
        <div className="flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => void answer("save")}>
            Save skill
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void answer("cancel")}>
            Cancel
          </Button>
        </div>
      )}
      {status === "saved" && (
        <p role="status" className="text-muted-foreground text-xs">
          Saved. Type /{str(card.slug)} to run it.
        </p>
      )}
      {status === "cancelled" && (
        <p role="status" className="text-muted-foreground text-xs">
          Not saved.
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </article>
  );
}

interface SystemMessageProps {
  message: Message;
  onOpenBot: (botId: string) => void;
  onOpenLibrary: (itemId: string) => void;
}

/** Cards and notes in the chat that are not something a person or a Bot said. */
export function SystemMessage({ message, onOpenBot, onOpenLibrary }: SystemMessageProps) {
  const card = message.card ?? {};
  if (card.type === "skill_draft") return <SkillDraftCard message={message} />;
  if (card.type === "file") {
    return (
      <div className="flex justify-center">
        <button
          type="button"
          aria-label={`Open ${str(card.title)} in the Library`}
          className="border-border hover:bg-muted flex max-w-[75%] items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm"
          onClick={() => onOpenLibrary(str(card.library_id))}
        >
          <FileText aria-hidden className="size-4 shrink-0" />
          <span className="min-w-0">
            <span className="block truncate font-medium">{str(card.title)}</span>
            <span className="text-muted-foreground block text-xs">In your Library</span>
          </span>
        </button>
      </div>
    );
  }
  if (card.type === "handoff") {
    return (
      <div className="flex justify-center">
        <Button
          size="sm"
          variant="outline"
          className="rounded-full"
          onClick={() => onOpenBot(str(card.bot_id))}
        >
          Passed to {str(card.bot_name)}
          <ArrowRight />
        </Button>
      </div>
    );
  }
  return message.content ? (
    <p className="text-muted-foreground text-center text-xs">{message.content}</p>
  ) : null;
}
