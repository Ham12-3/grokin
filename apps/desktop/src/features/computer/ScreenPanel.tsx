import { useState } from "react";
import { Screen } from "./Screen";
import { pauseRun, resumeRun, useComputer, useStartComputer, useStopComputer } from "./api";
import { Button } from "@/components/ui/button";
import type { Bot } from "@/features/bots/api";
import { useLiveStore } from "@/features/realtime/live";
import { errorMessage } from "@/lib/tauri";

const STATUS_TEXT = {
  starting: "Starting your computer, about 20 seconds...",
  running: "Running",
  paused: "Paused",
  stopped: "Off. It starts by itself when a Bot needs it.",
  error: "It could not start.",
} as const;

interface ScreenPanelProps {
  bot: Bot;
  /** The run in progress in this Bot's chat, if any. */
  activeRunId: string | undefined;
  /** True while the user has control (set by Take over or by the takeover card). */
  interactive: boolean;
  onInteractiveChange: (interactive: boolean) => void;
}

/** The Screen tab: computer status and controls, and the Bot's live screen. */
export function ScreenPanel({
  bot,
  activeRunId,
  interactive,
  onInteractiveChange,
}: ScreenPanelProps) {
  const computer = useComputer();
  const start = useStartComputer();
  const stop = useStopComputer();
  const liveStatus = useLiveStore((state) => state.computer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (computer.isPending) {
    return <p className="text-muted-foreground p-4 text-center text-sm">Loading...</p>;
  }
  if (computer.isError) {
    return (
      <div className="space-y-3 p-4 text-center">
        <p role="alert" className="text-destructive text-sm">
          {errorMessage(computer.error, "Could not load your computer.")}
        </p>
        <Button variant="outline" onClick={() => void computer.refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  const status = start.isPending ? "starting" : (liveStatus ?? computer.data.status);
  const working = start.isPending || stop.isPending || busy;
  const failure = error ?? (start.isError ? errorMessage(start.error) : null);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function takeOver() {
    // The Bot stops before its next step, so it does not fight you for the mouse.
    if (activeRunId) await act(() => pauseRun(activeRunId));
    onInteractiveChange(true);
  }

  async function giveBack() {
    onInteractiveChange(false);
    if (activeRunId) await act(() => resumeRun(activeRunId));
  }

  async function restart() {
    onInteractiveChange(false);
    await act(async () => {
      await stop.mutateAsync();
      await start.mutateAsync();
    });
  }

  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center justify-between gap-2 text-sm">
        <p>
          <span className="font-medium">Your computer: </span>
          <span className="text-muted-foreground" role="status">
            {STATUS_TEXT[status]}
          </span>
        </p>
      </div>

      {status === "running" && (
        <>
          <Screen computerId={computer.data.id} botId={bot.id} interactive={interactive} />
          <div className="flex flex-wrap gap-2">
            {interactive ? (
              <Button size="sm" disabled={working} onClick={() => void giveBack()}>
                Give back
              </Button>
            ) : (
              <Button size="sm" disabled={working} onClick={() => void takeOver()}>
                Take over
              </Button>
            )}
            <Button size="sm" variant="outline" disabled={working} onClick={() => void restart()}>
              Restart
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={working}
              onClick={() => {
                onInteractiveChange(false);
                stop.mutate();
              }}
            >
              Stop
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">
            {interactive
              ? "You are in control. Sign in or finish what only you can do, then give it back."
              : "You are watching. Take over to use the mouse and keyboard yourself."}
          </p>
        </>
      )}

      {(status === "stopped" || status === "error" || status === "paused") && (
        <Button size="sm" disabled={working} onClick={() => start.mutate()}>
          Start
        </Button>
      )}

      {failure && (
        <p role="alert" className="text-destructive text-xs">
          {failure}
        </p>
      )}
    </div>
  );
}
