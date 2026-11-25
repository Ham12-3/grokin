import { PanelRight, Star } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { cancelRun, flattenMessages, toolCallsByRun, useMessages, useSendMessage } from "./api";
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
  /** Opens the Screen tab with the user in control. */
  onOpenScreen: () => void;
  onGiveBack: (runId: string) => void;
}

export function ChatView({
  bot,
  chatId,
  working,
  onToggleDetails,
  onOpenScreen,
  onGiveBack,
}: ChatViewProps) {
  const messages = useMessages(chatId);
  const sendMessage = useSendMessage(chatId);
  const runError = useLiveStore((state) => state.errors[chatId]);
  const items = useMemo(() => flattenMessages(messages.data), [messages.data]);
  const toolCalls = useMemo(() => toolCallsByRun(messages.data), [messages.data]);
  const liveRunId = useLiveStore((state) => state.runs[chatId]);
  // After a restart the live store is empty: the newest page knows the run in progress.
  const activeRunId = liveRunId ?? messages.data?.pages[0]?.active_run_id ?? undefined;
  const [stopping, setStopping] = useState(false);
  const computerStatus = useLiveStore((state) => state.computer);
  // The Bot asked for help and is waiting: its request_takeover step is still running.
  const takeover = activeRunId
    ? toolCalls[activeRunId]?.find(
        // "pending" is what the live event says; "running" is what a refetch says.
        (step) =>
          step.tool === "request_takeover" &&
          (step.status === "pending" || step.status === "running"),
      )
    : undefined;

  // After a restart the live store is empty: remember the run the page told us about.
  const pageRunId = messages.data?.pages[0]?.active_run_id;
  useEffect(() => {
    if (pageRunId && !useLiveStore.getState().runs[chatId]) {
      useLiveStore.setState((state) => ({ runs: { ...state.runs, [chatId]: pageRunId } }));
    }
  }, [pageRunId, chatId]);

  async function stop(runId: string) {
    setStopping(true);
    try {
      await cancelRun(runId);
    } catch {
      // The run may have just finished; the next status event settles it.
    } finally {
      setStopping(false);
    }
  }
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
          toolCalls={toolCalls}
          hasOlder={messages.hasNextPage}
          loadingOlder={messages.isFetchingNextPage}
          onLoadOlder={loadOlder}
        />
      )}

      {takeover && activeRunId && (
        <div
          role="group"
          aria-label="Takeover request"
          className="border-border bg-muted/60 mx-4 mb-2 flex items-center gap-3 rounded-lg border px-3 py-2"
        >
          <p className="min-w-0 flex-1 text-sm">
            <span className="font-medium">{bot.name} needs you. </span>
            {takeover.summary.replace(/^Needs you: /, "")}
          </p>
          <Button size="sm" onClick={onOpenScreen}>
            Open screen
          </Button>
          <Button size="sm" variant="outline" onClick={() => onGiveBack(activeRunId)}>
            Give back
          </Button>
        </div>
      )}
      {working && computerStatus === "starting" && (
        <p role="status" className="text-muted-foreground px-4 pb-1 text-xs">
          Starting your computer, about 20 seconds...
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive px-4 pb-1 text-xs">
          {error}
        </p>
      )}
      <Composer
        botName={bot.name}
        busy={working || sendMessage.isPending}
        onStop={working && activeRunId && !stopping ? () => void stop(activeRunId) : undefined}
        onSend={(text) => {
          clearChatError(chatId);
          sendMessage.mutate(text);
        }}
      />
    </section>
  );
}
