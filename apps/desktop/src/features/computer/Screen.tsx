import RFB from "@novnc/novnc";
import { useEffect, useRef, useState } from "react";
import { screenUrl } from "./api";
import { apiBaseUrl, authGetAccessToken } from "@/lib/tauri";

type Link = "connecting" | "open" | "closed";

interface ScreenProps {
  computerId: string;
  botId: string;
  /** False = watch only. True = the user's mouse and keyboard reach the machine. */
  interactive: boolean;
}

/**
 * The live noVNC view of the Bot's screen. Passwords typed here go straight to the
 * computer: they never pass through the Bot or the chat.
 */
export function Screen({ computerId, botId, interactive }: ScreenProps) {
  const target = useRef<HTMLDivElement>(null);
  const rfb = useRef<RFB | null>(null);
  const [link, setLink] = useState<Link>("connecting");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    let client: RFB | null = null;
    setLink("connecting");

    void (async () => {
      try {
        const [base, token] = await Promise.all([apiBaseUrl(), authGetAccessToken()]);
        if (stopped || !target.current) return;
        client = new RFB(target.current, screenUrl(base, computerId, botId), {
          shared: true,
          wsProtocols: ["binary", "bearer." + token],
        });
        client.scaleViewport = true;
        client.viewOnly = true;
        client.addEventListener("connect", () => !stopped && setLink("open"));
        client.addEventListener("disconnect", () => !stopped && setLink("closed"));
        rfb.current = client;
      } catch {
        if (!stopped) setLink("closed");
      }
    })();

    return () => {
      stopped = true;
      rfb.current = null;
      try {
        client?.disconnect();
      } catch {
        // Already closed.
      }
    };
  }, [computerId, botId, attempt]);

  useEffect(() => {
    if (!rfb.current) return;
    rfb.current.viewOnly = !interactive;
    if (interactive) rfb.current.focus();
  }, [interactive, link]);

  return (
    <div className="space-y-1">
      <div
        ref={target}
        aria-label="Live screen"
        className={
          "bg-muted aspect-[16/10] w-full overflow-hidden rounded-md border " +
          (interactive ? "ring-2 ring-emerald-500" : "")
        }
      />
      {link === "connecting" && (
        <p className="text-muted-foreground text-xs">Connecting to the screen...</p>
      )}
      {link === "closed" && (
        <p className="text-muted-foreground text-xs">
          The screen is not connected.{" "}
          <button type="button" className="underline" onClick={() => setAttempt((n) => n + 1)}>
            Reconnect
          </button>
        </p>
      )}
    </div>
  );
}
