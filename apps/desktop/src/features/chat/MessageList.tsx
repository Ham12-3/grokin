import { useEffect, useLayoutEffect, useRef } from "react";
import { Markdown } from "./Markdown";
import type { Message } from "./api";
import { Button } from "@/components/ui/button";
import type { Bot } from "@/features/bots/api";
import { useLiveStore } from "@/features/realtime/live";
import { cn } from "@/lib/utils";

const NEAR_BOTTOM_PX = 80;

interface MessageListProps {
  bot: Bot;
  messages: Message[];
  hasOlder: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
}

function Bubble({ bot, message }: { bot: Bot; message: Message }) {
  const live = useLiveStore((state) => state.streaming[message.id]);
  const streaming = live !== undefined;
  const text = live ?? message.content;

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
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
      <div className="bg-muted max-w-[75%] rounded-2xl px-3 py-2" aria-busy={streaming}>
        <Markdown text={text} />
        {streaming && (
          <span
            aria-hidden
            className={cn(
              "bg-foreground/60 inline-block h-3 w-1.5 animate-pulse rounded-sm align-middle",
              text && "ml-0.5",
            )}
          />
        )}
      </div>
    </div>
  );
}

export function MessageList({
  bot,
  messages,
  hasOlder,
  loadingOlder,
  onLoadOlder,
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
        <Bubble key={message.id} bot={bot} message={message} />
      ))}
    </div>
  );
}
