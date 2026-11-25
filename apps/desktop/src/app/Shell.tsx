import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { DetailsPane, type DetailsTab } from "./DetailsPane";
import { Sidebar } from "./Sidebar";
import { Button } from "@/components/ui/button";
import { ApprovalsScreen } from "@/features/approvals/ApprovalsScreen";
import { useApprovals } from "@/features/approvals/api";
import { NewBotDialog } from "@/features/bots/NewBotDialog";
import { useBots, type Bot } from "@/features/bots/api";
import { ChatView } from "@/features/chat/ChatView";
import { resumeRun } from "@/features/computer/api";
import { startRealtime } from "@/features/realtime/connection";
import { useLiveStore } from "@/features/realtime/live";
import { apiFetch, type Schemas } from "@/lib/api/client";
import { authLogout, errorMessage, onOpenApprovals, setTrayBadge } from "@/lib/tauri";

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
  const [approvalsOpen, setApprovalsOpen] = useState(false);
  const approvals = useApprovals();
  const pending = approvals.data;
  const pendingCount = pending?.length ?? 0;
  const waitingBotIds = useMemo(
    () => new Set((pending ?? []).map((approval) => approval.bot_id)),
    [pending],
  );

  useEffect(() => startRealtime(queryClient), [queryClient]);

  // The tray shows how many approvals are waiting.
  useEffect(() => {
    void setTrayBadge(pendingCount).catch(() => undefined);
  }, [pendingCount]);

  // The tray menu, a notification, or Ctrl/Cmd+Shift+A opens the approvals.
  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;
    void onOpenApprovals(() => setApprovalsOpen(true))
      .then((unlisten) => {
        if (cancelled) unlisten();
        else stop = unlisten;
      })
      .catch(() => undefined);
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "a") {
        event.preventDefault();
        setApprovalsOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      cancelled = true;
      stop?.();
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const list = bots.data ?? [];
  // Fall back to the first Bot (the Primary Bot is listed first).
  const selected = list.find((bot) => bot.id === selectedId) ?? list[0] ?? null;
  const isWorking = (bot: Bot) => liveWorking[bot.id] ?? bot.working;
  const activeRunId = selected?.direct_chat_id ? liveRuns[selected.direct_chat_id] : undefined;

  function select(botId: string | null) {
    setApprovalsOpen(false);
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
          waitingBotIds={waitingBotIds}
          pendingApprovals={pendingCount}
          approvalsOpen={approvalsOpen}
          onOpenApprovals={() => setApprovalsOpen(true)}
          userLabel={me.data?.name ?? me.data?.email ?? ""}
          onSelect={select}
          onNewBot={() => setNewBotOpen(true)}
          onSignOut={() => void authLogout()}
        />

        {approvalsOpen && <ApprovalsScreen bots={list} onOpenBot={select} />}
        {!approvalsOpen && bots.isPending && (
          <p className="text-muted-foreground flex-1 p-8 text-center text-sm">Loading...</p>
        )}
        {!approvalsOpen && bots.isError && (
          <div className="flex-1 space-y-3 p-8 text-center">
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(bots.error, "Could not load your Bots.")}
            </p>
            <Button variant="outline" onClick={() => void bots.refetch()}>
              Retry
            </Button>
          </div>
        )}
        {!approvalsOpen && bots.isSuccess && !selected && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <h2 className="text-lg font-semibold">Create your first Bot</h2>
            <p className="text-muted-foreground max-w-sm text-sm">
              A Bot is a teammate with one narrow job, its own chat and its own memory.
            </p>
            <Button onClick={() => setNewBotOpen(true)}>New Bot</Button>
          </div>
        )}
        {!approvalsOpen && selected?.direct_chat_id && (
          <ChatView
            key={selected.direct_chat_id}
            bot={selected}
            chatId={selected.direct_chat_id}
            working={isWorking(selected)}
            approvals={(pending ?? []).filter(
              (approval) => approval.chat_id === selected.direct_chat_id,
            )}
            onToggleDetails={() => setDetailsOpen((open) => !open)}
            onOpenScreen={openScreen}
            onGiveBack={(runId) => void giveBack(runId)}
          />
        )}
        {!approvalsOpen && selected && detailsOpen && (
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
