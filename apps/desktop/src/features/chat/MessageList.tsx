import { useEffect, useLayoutEffect, useRef } from "react";
import { SystemMessage } from "./Cards";
import { Markdown } from "./Markdown";
import { RunDetails } from "./RunDetails";
import { ToolSteps } from "./ToolSteps";
import type { Message, ToolCall } from "./api";
import { Button } from "@/components/ui/button";
import type { Bot } from "@/features/bots/api";
import { useLiveStore } from "@/features/realtime/live";
import { cn } from "@/lib/utils";

const NEAR_BOTTOM_PX = 80;
const NO_STEPS: ToolCall[] = [];

interface MessageListProps {
  bot: Bot;
  messages: Message[];
  toolCalls: Record<string, ToolCall[]>;
  hasOlder: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  /** Opens another Bot's chat (from a handoff note). */
  onOpenBot: (botId: string) => void;
}

interface BubbleProps {
  bot: Bot;
  message: Message;
  steps: ToolCall[];
  onOpenBot: (botId: string) => void;
}

function Bubble({ bot, message, steps, onOpenBot }: BubbleProps) {
  const live = useLiveStore((state) => state.streaming[message.id]);
  const streaming = live !== undefined;
  const text = live ?? message.content;

  if (message.role === "system") {
    return <SystemMessage message={message} onOpenBot={onOpenBot} />;
  }
  if (message.role === "user") {
    // A task another Bot passed on, not something the user typed here.
    const from = message.card?.type === "handoff_from" ? message.card : null;
    return (
      <div className="flex flex-col items-end gap-0.5">
        {from && (
          <button
            type="button"
            className="text-muted-foreground text-xs underline"
            onClick={() => onOpenBot(String(from.bot_id))}
          >
            Passed on by {String(from.bot_name)}
          </button>
        )}
        <div className="bg-primary text-primary-foreground max-w-[75%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap">
          {text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2">
      <span aria-hidden className="mt-1 text-lg">
        {bot.avatar ?? "🤖"}
      </span>
      <div className="bg-muted max-w-[75%] space-y-2 rounded-2xl px-3 py-2" aria-busy={streaming}>
        {steps.length > 0 && <ToolSteps steps={steps} />}
        {text && <Markdown text={text} />}
        {streaming && (
          <span
            aria-hidden
            className={cn(
              "bg-foreground/60 inline-block h-3 w-1.5 animate-pulse rounded-sm align-middle",
              text && "ml-0.5",
            )}
          />
        )}
        {!streaming && message.run_id && <RunDetails runId={message.run_id} steps={steps} />}
      </div>
    </div>
  );
}

export function MessageList({
  bot,
  messages,
  toolCalls,
  hasOlder,
  loadingOlder,
  onLoadOlder,
  onOpenBot,
}: MessageListProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const topSentinel = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const previousHeight = useRef(0);
  const firstId = messages[0]?.id;
  const lastId = messages[messages.length - 1]?.id;
  // Follow the text of the newest message while it streams.
  const liveLength = useLiveStore((state) => (lastId ? state.streaming[lastId]?.length : 0));

  // Keep the view steady when older messages are added above.
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) return;
    if (!stickToBottom.current && previousHeight.current) {
      element.scrollTop += element.scrollHeight - previousHeight.current;
    }
    previousHeight.current = element.scrollHeight;
  }, [firstId]);

  // Stay at the bottom as new text arrives, unless the user scrolled up to read.
  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
    if (element) previousHeight.current = element.scrollHeight;
  }, [lastId, liveLength]);

  // Something below the list (an approval card) can make it shorter: stay at the bottom.
  useEffect(() => {
    const element = scroller.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stickToBottom.current) element.scrollTop = element.scrollHeight;
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Load older messages when the top comes into view.
  useEffect(() => {
    const sentinel = topSentinel.current;
    if (!sentinel || !hasOlder || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !loadingOlder) onLoadOlder();
      },
      { root: scroller.current },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasOlder, loadingOlder, onLoadOlder]);

  function onScroll() {
    const element = scroller.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    stickToBottom.current = distance < NEAR_BOTTOM_PX;
  }

  return (
    <div
      ref={scroller}
      onScroll={onScroll}
      className="flex-1 space-y-3 overflow-y-auto p-4"
      role="log"
      aria-label={`Chat with ${bot.name}`}
    >
      <div ref={topSentinel} />
      {hasOlder && (
        <div className="flex justify-center">
          <Button variant="ghost" size="sm" disabled={loadingOlder} onClick={onLoadOlder}>
            {loadingOlder ? "Loading..." : "Load earlier messages"}
          </Button>
        </div>
      )}
      {messages.length === 0 && !hasOlder && (
        <p className="text-muted-foreground pt-16 text-center text-sm">
          Say hello to {bot.name}. {bot.job}
        </p>
      )}
      {messages.map((message) => (
        <Bubble
          key={message.id}
          bot={bot}
          message={message}
          steps={(message.run_id && toolCalls[message.run_id]) || NO_STEPS}
          onOpenBot={onOpenBot}
        />
      ))}
    </div>
  );
}
