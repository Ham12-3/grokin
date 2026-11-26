import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useLiveStore } from "@/features/realtime/live";
import { appVersion, onUpdateReady, updateRestart, updateStatus } from "@/lib/tauri";

/** The version a downloaded update would bring, kept current by the Rust core's events. */
function useUpdateReady(): string | null {
  const [ready, setReady] = useState<string | null>(null);
  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;
    void updateStatus()
      .then((version) => !cancelled && version && setReady(version))
      .catch(() => undefined);
    void onUpdateReady((version) => setReady(version))
      .then((unlisten) => {
        if (cancelled) unlisten();
        else stop = unlisten;
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      stop?.();
    };
  }, []);
  return ready;
}

/** True while any Bot is in the middle of a reply: not the moment to restart. */
function useAnyBotWorking(): boolean {
  return useLiveStore((state) => Object.keys(state.runs).length > 0);
}

/** This version, and "Update ready, restart" when one has been downloaded. */
export function UpdatesSection() {
  const version = useQuery({ queryKey: ["app-version"], queryFn: appVersion, staleTime: Infinity });
  const ready = useUpdateReady();
  const working = useAnyBotWorking();

  return (
    <section aria-label="Updates" className="space-y-2">
      <h3 className="text-sm font-semibold">Updates</h3>
      <p className="text-muted-foreground text-xs">
        Crew {version.data ?? ""}. It checks for updates when it starts and every 6 hours.
      </p>
      {ready ? (
        <div className="space-y-1">
          <p role="status" className="text-sm">
            Update ready: version {ready}.
          </p>
          <Button size="sm" disabled={working} onClick={() => void updateRestart()}>
            Restart to update
          </Button>
          {working && (
            <p className="text-muted-foreground text-xs">
              A Bot is working. You can restart when it has finished.
            </p>
          )}
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">You are up to date.</p>
      )}
    </section>
  );
}
