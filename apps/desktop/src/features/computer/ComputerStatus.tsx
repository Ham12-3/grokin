import { useComputer, useStartComputer, useStopComputer } from "./api";
import { Button } from "@/components/ui/button";
import { useLiveStore } from "@/features/realtime/live";
import { errorMessage } from "@/lib/tauri";

const STATUS_TEXT = {
  starting: "Starting...",
  running: "Running",
  paused: "Paused",
  stopped: "Off. It starts by itself when a Bot needs it.",
  error: "It could not start.",
} as const;

interface ComputerStatusProps {
  /** Called before the computer stops or restarts, so a Take over ends first. */
  onStopping: () => void;
}

/** Settings: the state of the user's computer, with Start, Stop and Restart. */
export function ComputerStatus({ onStopping }: ComputerStatusProps) {
  const computer = useComputer();
  const start = useStartComputer();
  const stop = useStopComputer();
  const liveStatus = useLiveStore((state) => state.computer);

  if (!computer.data) return null;
  const working = start.isPending || stop.isPending;
  const status = start.isPending ? "starting" : (liveStatus ?? computer.data.status);
  const failed = start.error ?? stop.error;

  async function restart() {
    onStopping();
    try {
      await stop.mutateAsync();
      await start.mutateAsync();
    } catch {
      // Shown below through the mutation's error.
    }
  }

  return (
    <section aria-label="Your computer" className="space-y-2 border-t pt-4">
      <h3 className="text-sm font-medium">Your computer</h3>
      <p className="text-muted-foreground text-sm" role="status">
        {STATUS_TEXT[status]}
      </p>
      <p className="text-muted-foreground text-xs">
        All your Bots share it. Files and sign-ins are kept when it stops.
      </p>
      <div className="flex flex-wrap gap-2">
        {status === "running" ? (
          <>
            <Button size="sm" variant="outline" disabled={working} onClick={() => void restart()}>
              Restart
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={working}
              onClick={() => {
                onStopping();
                stop.mutate();
              }}
            >
              Stop
            </Button>
          </>
        ) : (
          <Button size="sm" disabled={working} onClick={() => start.mutate()}>
            Start
          </Button>
        )}
      </div>
      {failed && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(failed)}
        </p>
      )}
    </section>
  );
}
