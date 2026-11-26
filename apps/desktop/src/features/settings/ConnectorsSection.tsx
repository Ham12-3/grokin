import { useState, type FormEvent } from "react";
import { useConnectorActions, useConnectors, type Connector } from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage, openExternal } from "@/lib/tauri";

function McpTools({ connector }: { connector: Connector }) {
  const { setSafeTools } = useConnectorActions();
  const tools = connector.tools ?? [];
  const safe = tools.filter((tool) => tool.safe).map((tool) => tool.name);
  if (tools.length === 0) {
    return <p className="text-muted-foreground text-xs">This server has no tools.</p>;
  }
  return (
    <ul aria-label={`Tools of ${connector.name}`} className="space-y-1 pt-1">
      {tools.map((tool) => (
        <li key={tool.name} className="text-xs">
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={tool.safe}
              disabled={setSafeTools.isPending}
              aria-label={`${tool.name} runs without asking`}
              onChange={(event) =>
                setSafeTools.mutate({
                  id: connector.id,
                  safeTools: event.target.checked
                    ? [...safe, tool.name]
                    : safe.filter((name) => name !== tool.name),
                })
              }
            />
            <span className="min-w-0">
              <span className="font-medium">{tool.name}</span>{" "}
              <span className="text-muted-foreground">
                {tool.safe ? "runs without asking" : "asks every time"}
              </span>
              {tool.description && (
                <span className="text-muted-foreground block break-words">{tool.description}</span>
              )}
            </span>
          </label>
        </li>
      ))}
    </ul>
  );
}

/** Apps your Bots can use, and your own MCP servers. */
export function ConnectorsSection() {
  const connectors = useConnectors();
  const { connect, addMcp, disconnect } = useConnectorActions();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const data = connectors.data;
  const byKind = new Map(data?.connected.map((item) => [item.kind, item]));
  const servers = data?.connected.filter((item) => item.kind === "mcp") ?? [];
  const failed = connect.error ?? addMcp.error ?? disconnect.error;

  function start(kind: string) {
    connect.mutate(kind, {
      // Sign-in happens in your browser; the app never sees the password.
      onSuccess: (started) => (started.url ? void openExternal(started.url) : undefined),
    });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !url.trim()) return;
    addMcp.mutate(
      { name: name.trim(), url: url.trim(), headers_secret_ref: secret.trim() || null },
      {
        onSuccess: () => {
          setName("");
          setUrl("");
          setSecret("");
        },
      },
    );
  }

  return (
    <section aria-label="Connectors" className="space-y-3">
      <header>
        <h3 className="text-sm font-semibold">Connectors</h3>
        <p className="text-muted-foreground text-xs">
          Connect an app here, then choose which Bots may use it in each Bot&apos;s Apps tab.
        </p>
      </header>
      {connectors.isError && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(connectors.error, "Could not load connectors.")}
        </p>
      )}
      {data && !data.configured && (
        <p role="status" className="text-muted-foreground text-xs">
          Apps cannot be connected on this server yet (no connector service is set up).
        </p>
      )}
      <ul aria-label="Apps" className="space-y-1">
        {data?.available.map((app) => {
          const connected = byKind.get(app.kind);
          return (
            <li key={app.kind} className="flex items-center gap-2 text-sm">
              <span className="flex-1">{app.name}</span>
              {connected && (
                <span className="text-muted-foreground text-xs">
                  {connected.status === "connected"
                    ? "Connected"
                    : connected.status === "pending"
                      ? "Finish in your browser"
                      : "Needs reconnecting"}
                </span>
              )}
              {connected?.status === "pending" && (
                <Button size="sm" variant="outline" onClick={() => void connectors.refetch()}>
                  Check
                </Button>
              )}
              {connected ? (
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`Disconnect ${app.name}`}
                  disabled={disconnect.isPending}
                  onClick={() => disconnect.mutate(connected.id)}
                >
                  Disconnect
                </Button>
              ) : (
                <Button
                  size="sm"
                  aria-label={`Connect ${app.name}`}
                  disabled={connect.isPending || !data.configured}
                  onClick={() => start(app.kind)}
                >
                  Connect
                </Button>
              )}
            </li>
          );
        })}
      </ul>

      <h4 className="pt-2 text-sm font-medium">Custom MCP servers</h4>
      {servers.map((server) => (
        <div key={server.id} className="border-border space-y-1 rounded-md border p-2">
          <div className="flex items-center gap-2">
            <p className="min-w-0 flex-1 text-sm font-medium break-words">{server.name}</p>
            <Button
              size="sm"
              variant="outline"
              aria-label={`Remove ${server.name}`}
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate(server.id)}
            >
              Remove
            </Button>
          </div>
          <p className="text-muted-foreground text-xs break-all">{server.url}</p>
          <McpTools connector={server} />
        </div>
      ))}
      <form className="space-y-2" onSubmit={submit}>
        <div className="space-y-1">
          <Label htmlFor="mcp-name">Name</Label>
          <Input id="mcp-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="mcp-url">Address</Label>
          <Input
            id="mcp-url"
            placeholder="https://example.com/mcp"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="mcp-secret">Vault item with its headers (optional)</Label>
          <Input
            id="mcp-secret"
            placeholder="for example tickets_headers"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        </div>
        <Button type="submit" size="sm" disabled={addMcp.isPending || !name.trim() || !url.trim()}>
          Add MCP server
        </Button>
      </form>
      {failed && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(failed)}
        </p>
      )}
    </section>
  );
}
