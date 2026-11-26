import { useBotApps, useConnectors, useSetBotApps } from "./api";
import type { Bot } from "@/features/bots/api";
import { errorMessage } from "@/lib/tauri";

/** Which connected apps this Bot may use. A Bot has no app tools unless ticked here. */
export function AppsTab({ bot, onOpenSettings }: { bot: Bot; onOpenSettings: () => void }) {
  const connectors = useConnectors();
  const apps = useBotApps(bot.id);
  const setApps = useSetBotApps(bot.id);
  const connected = connectors.data?.connected.filter((item) => item.status === "connected");
  const allowed = apps.data?.connector_ids ?? [];
  const failed = connectors.error ?? apps.error ?? setApps.error;

  return (
    <div className="space-y-3 pt-2">
      <p className="text-muted-foreground text-xs">
        {bot.name} can only use the apps you tick here.
      </p>
      {(connectors.isPending || apps.isPending) && (
        <p className="text-muted-foreground text-sm">Loading...</p>
      )}
      {connected?.length === 0 && (
        <p className="text-muted-foreground text-sm">No apps are connected yet.</p>
      )}
      <ul aria-label="Apps" className="space-y-1">
        {apps.isSuccess &&
          connected?.map((connector) => (
            <li key={connector.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={allowed.includes(connector.id)}
                  disabled={setApps.isPending}
                  onChange={(event) =>
                    setApps.mutate(
                      event.target.checked
                        ? [...allowed, connector.id]
                        : allowed.filter((id) => id !== connector.id),
                    )
                  }
                />
                {connector.name}
                {connector.kind === "mcp" && (
                  <span className="text-muted-foreground text-xs">MCP server</span>
                )}
              </label>
            </li>
          ))}
      </ul>
      <button type="button" className="text-xs underline" onClick={onOpenSettings}>
        Connect more apps in Settings
      </button>
      {failed && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(failed)}
        </p>
      )}
    </div>
  );
}
