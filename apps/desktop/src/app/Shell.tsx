import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { DetailsPane, type DetailsTab } from "./DetailsPane";
import { Sidebar } from "./Sidebar";
import { Button } from "@/components/ui/button";
import { NewBotDialog } from "@/features/bots/NewBotDialog";
import { useBots, type Bot } from "@/features/bots/api";
import { ChatView } from "@/features/chat/ChatView";
import { resumeRun } from "@/features/computer/api";
import { startRealtime } from "@/features/realtime/connection";
import { useLiveStore } from "@/features/realtime/live";
import { apiFetch, type Schemas } from "@/lib/api/client";
import { authLogout, errorMessage } from "@/lib/tauri";

/** The signed-in app: sidebar, chat and the details pane. */
export function Shell() {
  const queryClient = useQueryClient();
  const bots = useBots();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<Schemas["MeResponse"]>("/me"),
  });
  const status = useLiveStore((state) => state.status);
  const liveWorking = useLiveStore((state) => state.working);
  const liveRuns = useLiveStore((state) => state.runs);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsTab, setDetailsTab] = useState<DetailsTab>("settings");
  // True while the user is in control of the screen (Take over).
  const [interactive, setInteractive] = useState(false);
  const [newBotOpen, setNewBotOpen] = useState(false);

  useEffect(() => startRealtime(queryClient), [queryClient]);

  const list = bots.data ?? [];
  // Fall back to the first Bot (the Primary Bot is listed first).
  const selected = list.find((bot) => bot.id === selectedId) ?? list[0] ?? null;
  const isWorking = (bot: Bot) => liveWorking[bot.id] ?? bot.working;
  const activeRunId = selected?.direct_chat_id ? liveRuns[selected.direct_chat_id] : undefined;

  function select(botId: string | null) {
    setSelectedId(botId);
    setInteractive(false); // control never carries over to another Bot's screen
  }

  function openScreen() {
    setDetailsOpen(true);
    setDetailsTab("screen");
    setInteractive(true);
  }

  async function giveBack(runId: string) {
    setInteractive(false);
    try {
      await resumeRun(runId);
    } catch {
      // The run may have just ended; the next status event settles it.
    }
  }

  return (
    <div className="bg-background text-foreground flex h-screen flex-col">
      {status === "reconnecting" && (
        <div role="status" className="bg-amber-500/15 px-4 py-1 text-center text-xs">
          Reconnecting...
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar
          bots={list}
          selectedId={selected?.id ?? null}
          isWorking={isWorking}
          userLabel={me.data?.name ?? me.data?.email ?? ""}
          onSelect={select}
          onNewBot={() => setNewBotOpen(true)}
          onSignOut={() => void authLogout()}
        />

        {bots.isPending && (
          <p className="text-muted-foreground flex-1 p-8 text-center text-sm">Loading...</p>
        )}
        {bots.isError && (
          <div className="flex-1 space-y-3 p-8 text-center">
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(bots.error, "Could not load your Bots.")}
            </p>
            <Button variant="outline" onClick={() => void bots.refetch()}>
              Retry
            </Button>
          </div>
        )}
        {bots.isSuccess && !selected && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <h2 className="text-lg font-semibold">Create your first Bot</h2>
            <p className="text-muted-foreground max-w-sm text-sm">
              A Bot is a teammate with one narrow job, its own chat and its own memory.
            </p>
            <Button onClick={() => setNewBotOpen(true)}>New Bot</Button>
          </div>
        )}
        {selected?.direct_chat_id && (
          <ChatView
            key={selected.direct_chat_id}
            bot={selected}
            chatId={selected.direct_chat_id}
            working={isWorking(selected)}
            onToggleDetails={() => setDetailsOpen((open) => !open)}
            onOpenScreen={openScreen}
            onGiveBack={(runId) => void giveBack(runId)}
          />
        )}
        {selected && detailsOpen && (
          <DetailsPane
            key={selected.id}
            bot={selected}
            tab={detailsTab}
            onTabChange={setDetailsTab}
            activeRunId={activeRunId}
            interactive={interactive}
            onInteractiveChange={setInteractive}
            onDeleted={() => select(null)}
          />
        )}
      </div>

      <NewBotDialog open={newBotOpen} onOpenChange={setNewBotOpen} onCreated={select} />
    </div>
  );
}
