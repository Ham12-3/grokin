import { PanelRight, Star } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { flattenMessages, useMessages, useSendMessage } from "./api";
import { Button } from "@/components/ui/button";
import type { Bot } from "@/features/bots/api";
import { StatusDot } from "@/features/bots/StatusDot";
import { subscribeChat } from "@/features/realtime/connection";
import { clearChatError, useLiveStore } from "@/features/realtime/live";
import { errorMessage } from "@/lib/tauri";

interface ChatViewProps {
  bot: Bot;
  chatId: string;
  working: boolean;
  onToggleDetails: () => void;
}

export function ChatView({ bot, chatId, working, onToggleDetails }: ChatViewProps) {
  const messages = useMessages(chatId);
  const sendMessage = useSendMessage(chatId);
  const runError = useLiveStore((state) => state.errors[chatId]);
  const items = useMemo(() => flattenMessages(messages.data), [messages.data]);
  const { fetchNextPage } = messages;
  const loadOlder = useCallback(() => void fetchNextPage(), [fetchNextPage]);

  useEffect(() => subscribeChat(chatId), [chatId]);

  const sendError = sendMessage.isError ? errorMessage(sendMessage.error) : null;
  const error = sendError ?? runError;

  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="border-border flex items-center gap-2 border-b px-4 py-2">
        <span aria-hidden className="text-xl">
          {bot.avatar ?? "🤖"}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="flex items-center gap-1.5 truncate text-sm font-semibold">
            {bot.name}
            {bot.is_primary && (
              <Star aria-label="Primary Bot" className="size-3 fill-current text-amber-500" />
            )}
            <StatusDot working={working} />
          </h2>
          <p className="text-muted-foreground truncate text-xs">{bot.job}</p>
        </div>
        <Button variant="ghost" size="icon" aria-label="Toggle details" onClick={onToggleDetails}>
          <PanelRight />
        </Button>
      </header>

      {messages.isPending && (
        <p className="text-muted-foreground flex-1 p-6 text-center text-sm">Loading messages...</p>
      )}
      {messages.isError && (
        <div className="flex-1 space-y-3 p-6 text-center">
          <p role="alert" className="text-destructive text-sm">
            {errorMessage(messages.error, "Could not load this chat.")}
          </p>
          <Button variant="outline" onClick={() => void messages.refetch()}>
            Retry
          </Button>
        </div>
      )}
      {messages.isSuccess && (
        <MessageList
          bot={bot}
          messages={items}
          hasOlder={messages.hasNextPage}
          loadingOlder={messages.isFetchingNextPage}
          onLoadOlder={loadOlder}
        />
      )}

      {error && (
        <p role="alert" className="text-destructive px-4 pb-1 text-xs">
          {error}
        </p>
      )}
      <Composer
        botName={bot.name}
        busy={working || sendMessage.isPending}
        onSend={(text) => {
          clearChatError(chatId);
          sendMessage.mutate(text);
        }}
      />
    </section>
  );
}
