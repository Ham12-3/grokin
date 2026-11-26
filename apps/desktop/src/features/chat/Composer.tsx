import { SendHorizontal, Square, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { Skill } from "@/features/skills/api";
import { cn } from "@/lib/utils";

interface ComposerProps {
  botName: string;
  /** True while the Bot is replying or the message is being sent. */
  busy: boolean;
  /** This Bot's skills, for the "/" picker. */
  skills?: Skill[];
  /** Group chats: the Bots that can be mentioned with "@". */
  mentions?: { id: string; name: string; avatar?: string | null }[];
  onSend: (text: string, skillId?: string) => void;
  /** Present while a run can be stopped: the Send button becomes Stop. */
  onStop?: () => void;
}

/** "/" then letters, nothing else yet: the user is choosing a skill. */
const PICKING = /^\/([\w-]*)$/;

/** "@" then letters at the end of the text: the user is choosing a Bot to mention. */
const MENTIONING = /(^|\s)@([\w]*)$/;

export function Composer({
  botName,
  busy,
  skills = [],
  mentions = [],
  onSend,
  onStop,
}: ComposerProps) {
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<Skill | null>(null);
  const [highlight, setHighlight] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  const query = picked || dismissed ? null : (PICKING.exec(text)?.[1].toLowerCase() ?? null);
  const matches =
    query === null
      ? []
      : skills.filter(
          (skill) => skill.slug.includes(query) || skill.name.toLowerCase().includes(query),
        );
  const open = query !== null;
  const typed = dismissed ? null : (MENTIONING.exec(text)?.[2].toLowerCase() ?? null);
  const people =
    typed === null || mentions.length === 0
      ? []
      : mentions.filter((bot) => bot.name.toLowerCase().replace(/\s/g, "").includes(typed));
  const mentioning = people.length > 0;
  const active = Math.min(highlight, Math.max((mentioning ? people : matches).length - 1, 0));

  function mention(name: string) {
    setText(text.replace(MENTIONING, (_all, space: string) => `${space}@${name} `));
    setHighlight(0);
  }
  const canSend = !busy && (text.trim().length > 0 || picked !== null);

  function pick(skill: Skill) {
    setPicked(skill);
    setText("");
    setHighlight(0);
  }

  function send() {
    if (!canSend) return;
    if (picked) onSend(`/${picked.slug} ${text.trim()}`.trim(), picked.id);
    else onSend(text.trim());
    setText("");
    setPicked(null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (mentioning) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setHighlight((active + step + people.length) % people.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        mention(people[active].name);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissed(true);
        return;
      }
    }
    if (open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setHighlight((active + step + matches.length) % Math.max(matches.length, 1));
        return;
      }
      if ((event.key === "Enter" || event.key === "Tab") && matches[active]) {
        event.preventDefault();
        pick(matches[active]);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissed(true);
        return;
      }
    }
    if (event.key === "Backspace" && picked && text === "") {
      setPicked(null);
      return;
    }
    // Enter sends, Shift+Enter adds a line. Leave Enter alone while an IME is composing.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  return (
    <div className="border-border relative border-t p-3">
      {mentioning && (
        <ul
          role="listbox"
          aria-label="Bots"
          className="border-border bg-popover absolute right-3 bottom-full left-3 mb-1 max-h-56 overflow-y-auto rounded-md border p-1 shadow-md"
        >
          {people.map((bot, index) => (
            <li
              key={bot.id}
              role="option"
              aria-selected={index === active}
              className={cn(
                "cursor-pointer rounded px-2 py-1.5 text-sm",
                index === active && "bg-accent",
              )}
              onMouseDown={(event) => {
                event.preventDefault();
                mention(bot.name);
              }}
            >
              <span aria-hidden>{bot.avatar ?? "🤖"}</span> {bot.name}
            </li>
          ))}
        </ul>
      )}
      {open && !mentioning && (
        <ul
          role="listbox"
          aria-label="Skills"
          className="border-border bg-popover absolute right-3 bottom-full left-3 mb-1 max-h-56 overflow-y-auto rounded-md border p-1 shadow-md"
        >
          {matches.length === 0 && (
            <li className="text-muted-foreground px-2 py-1.5 text-xs">
              {skills.length === 0
                ? "No skills yet. Create one in the Skills tab."
                : "No skill matches."}
            </li>
          )}
          {matches.map((skill, index) => (
            <li
              key={skill.id}
              role="option"
              aria-selected={index === active}
              className={cn(
                "cursor-pointer rounded px-2 py-1.5 text-sm",
                index === active && "bg-accent",
              )}
              onMouseDown={(event) => {
                event.preventDefault(); // keep the focus in the text box
                pick(skill);
              }}
            >
              <span className="font-medium">/{skill.slug}</span>{" "}
              <span className="text-muted-foreground">{skill.description || skill.name}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2">
        {picked && (
          <span className="bg-muted flex h-9 shrink-0 items-center gap-1 rounded-md pr-1 pl-2 text-sm">
            /{picked.slug}
            <button
              type="button"
              aria-label="Remove skill"
              className="text-muted-foreground hover:text-foreground"
              onClick={() => setPicked(null)}
            >
              <X className="size-3.5" />
            </button>
          </span>
        )}
        <Textarea
          aria-label={`Message ${botName}`}
          placeholder={picked ? "Add details (optional)" : `Message ${botName}`}
          rows={1}
          className="max-h-40 min-h-9 resize-none"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setDismissed(false);
          }}
          onKeyDown={onKeyDown}
        />
        {onStop ? (
          <Button type="button" size="icon" variant="outline" aria-label="Stop" onClick={onStop}>
            <Square className="fill-current" />
          </Button>
        ) : (
          <Button type="button" size="icon" aria-label="Send" disabled={!canSend} onClick={send}>
            <SendHorizontal />
          </Button>
        )}
      </div>
    </div>
  );
}
