import { SendHorizontal } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ComposerProps {
  botName: string;
  /** True while the Bot is replying or the message is being sent. */
  busy: boolean;
  onSend: (text: string) => void;
}

export function Composer({ botName, busy, onSend }: ComposerProps) {
  const [text, setText] = useState("");
  const canSend = !busy && text.trim().length > 0;

  function send() {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter adds a line. Leave Enter alone while an IME is composing.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  return (
    <div className="border-border flex items-end gap-2 border-t p-3">
      <Textarea
        aria-label={`Message ${botName}`}
        placeholder={`Message ${botName}`}
        rows={1}
        className="max-h-40 min-h-9 resize-none"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <Button type="button" size="icon" aria-label="Send" disabled={!canSend} onClick={send}>
        <SendHorizontal />
      </Button>
    </div>
  );
}
