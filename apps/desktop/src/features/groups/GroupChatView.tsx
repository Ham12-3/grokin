import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useGroupActions, type Chat } from "./api";
import { Button } from "@/components/ui/button";
import type { Bot } from "@/features/bots/api";
import { Composer } from "@/features/chat/Composer";
import { MessageList } from "@/features/chat/MessageList";
import {
  cancelRun,
  flattenMessages,
  toolCallsByRun,
  useMessages,
  useSendMessage,
} from "@/features/chat/api";
import { subscribeChat } from "@/features/realtime/connection";
import { clearChatError, dropChatStreaming, useLiveStore } from "@/features/realtime/live";
import { errorMessage } from "@/lib/tauri";

interface GroupChatViewProps {
  chat: Chat;
  bots: Bot[];
  onOpenBot: (botId: string) => void;
  onOpenLibrary: (itemId: string) => void;
  onDeleted: () => void;
}

/** A chat with several Bots. `@Name` asks one directly; otherwise one of them is chosen. */
export function GroupChatView({
  chat,
  bots,
  onOpenBot,
  onOpenLibrary,
  onDeleted,
}: GroupChatViewProps) {
  const queryClient = useQueryClient();
  const members = useMemo(
    () => bots.filter((bot) => chat.bot_ids.includes(bot.id)),
    [bots, chat.bot_ids],
  );
  const messages = useMessages(chat.id);
  const sendMessage = useSendMessage(chat.id);
  const { remove } = useGroupActions();
  const items = useMemo(() => flattenMessages(messages.data), [messages.data]);
  const toolCalls = useMemo(() => toolCallsByRun(messages.data), [messages.data]);
  const liveRunId = useLiveStore((state) => state.runs[chat.id]);
  const runError = useLiveStore((state) => state.errors[chat.id]);
  const activeRunId = liveRunId ?? messages.data?.pages[0]?.active_run_id ?? undefined;
  const [stopping, setStopping] = useState(false);
  const { fetchNextPage } = messages;
  const loadOlder = useCallback(() => void fetchNextPage(), [fetchNextPage]);

  useEffect(() => {
    const unsubscribe = subscribeChat(chat.id);
    return () => {
      unsubscribe();
      dropChatStreaming(queryClient, chat.id);
    };
  }, [chat.id, queryClient]);

  async function stop(runId: string) {
    setStopping(true);
    try {
      await cancelRun(runId);
    } catch {
      // It may have just finished.
    } finally {
      setStopping(false);
    }
  }

  const first = members[0] ?? bots[0];
  const error = (sendMessage.isError ? errorMessage(sendMessage.error) : null) ?? runError;
  if (!first) return null;

  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="border-border flex items-center gap-2 border-b px-4 py-2">
        <span aria-hidden className="text-xl">
          {members
            .slice(0, 3)
            .map((bot) => bot.avatar ?? "🤖")
            .join("")}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">{chat.title ?? "Group chat"}</h2>
          <p className="text-muted-foreground truncate text-xs">
            {members.length} Bots. Mention one with @ to ask it directly.
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Delete group chat"
          disabled={remove.isPending}
          onClick={() => remove.mutate(chat.id, { onSuccess: onDeleted })}
        >
          <Trash2 />
        </Button>
      </header>
      {messages.isPending && (
        <p className="text-muted-foreground flex-1 p-6 text-center text-sm">Loading messages...</p>
      )}
      {messages.isError && (
        <p role="alert" className="text-destructive flex-1 p-6 text-center text-sm">
          {errorMessage(messages.error, "Could not load this chat.")}
        </p>
      )}
      {messages.isSuccess && (
        <MessageList
          bot={first}
          bots={members}
          label={chat.title ?? "Group chat"}
          messages={items}
          toolCalls={toolCalls}
          hasOlder={messages.hasNextPage}
          loadingOlder={messages.isFetchingNextPage}
          onLoadOlder={loadOlder}
          onOpenBot={onOpenBot}
          onOpenLibrary={onOpenLibrary}
        />
      )}
      {error && (
        <p role="alert" className="text-destructive px-4 pb-1 text-xs">
          {error}
        </p>
      )}
      <Composer
        botName={chat.title ?? "the group"}
        busy={Boolean(activeRunId) || sendMessage.isPending}
        mentions={members}
        onStop={activeRunId && !stopping ? () => void stop(activeRunId) : undefined}
        onSend={(text) => {
          clearChatError(chat.id);
          sendMessage.mutate({ content: text });
        }}
      />
    </section>
  );
}
