/**
 * The app's single WebSocket. Reconnects with backoff (1s, 2s, 4s ... max 30s) and
 * re-subscribes to the open chats. The access token travels as a subprotocol, never in
 * the URL, so it does not end up in server logs.
 */

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed";

export interface ServerEvent {
  type: string;
  [key: string]: unknown;
}

export interface WsOptions {
  getUrl: () => Promise<string>;
  /** `force` asks for a brand-new token (after the server closed us for an expired one). */
  getToken: (force: boolean) => Promise<string>;
  onEvent: (event: ServerEvent) => void;
  onStatus: (status: WsStatus) => void;
  /** Called after a reconnect, so the app can refetch what it may have missed. */
  onReconnected: () => void;
  createSocket?: (url: string, protocols: string[]) => WebSocket;
}

const PROTOCOL = "crew.v1";
const MAX_BACKOFF_MS = 30_000;
const PING_MS = 25_000;
const CLOSE_UNAUTHORIZED = 4401;

export function backoffMs(attempt: number): number {
  return Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
}

export function wsUrl(apiBase: string): string {
  return `${apiBase.replace(/^http/, "ws")}/api/v1/ws`;
}

export class WsClient {
  private socket: WebSocket | null = null;
  private readonly chats = new Set<string>();
  private attempt = 0;
  private stopped = true;
  private connectedBefore = false;
  private forceToken = false;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private pingTimer: ReturnType<typeof setInterval> | undefined;

  constructor(private readonly options: WsOptions) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.retryTimer);
    clearInterval(this.pingTimer);
    this.socket?.close();
    this.socket = null;
    this.options.onStatus("closed");
  }

  subscribe(chatId: string): void {
    this.chats.add(chatId);
    this.send({ type: "subscribe", chat_id: chatId });
  }

  unsubscribe(chatId: string): void {
    this.chats.delete(chatId);
    this.send({ type: "unsubscribe", chat_id: chatId });
  }

  private send(message: Record<string, string>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  private async connect(): Promise<void> {
    this.options.onStatus(this.connectedBefore ? "reconnecting" : "connecting");
    let socket: WebSocket;
    try {
      const [url, token] = await Promise.all([
        this.options.getUrl(),
        this.options.getToken(this.forceToken),
      ]);
      if (this.stopped) return;
      const protocols = [PROTOCOL, `bearer.${token}`];
      socket = this.options.createSocket
        ? this.options.createSocket(url, protocols)
        : new WebSocket(url, protocols);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.forceToken = false;
      this.options.onStatus("open");
      for (const chatId of this.chats) this.send({ type: "subscribe", chat_id: chatId });
      if (this.connectedBefore) this.options.onReconnected();
      this.connectedBefore = true;
      clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.send({ type: "ping" }), PING_MS);
    };
    socket.onmessage = (message) => {
      try {
        const event: unknown = JSON.parse(String(message.data));
        if (typeof event === "object" && event !== null && "type" in event) {
          this.options.onEvent(event as ServerEvent);
        }
      } catch {
        // Ignore anything that is not a JSON event.
      }
    };
    socket.onclose = (close) => {
      if (this.socket !== socket) return;
      this.socket = null;
      clearInterval(this.pingTimer);
      if (this.stopped) return;
      if (close.code === CLOSE_UNAUTHORIZED) this.forceToken = true;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.options.onStatus(this.connectedBefore ? "reconnecting" : "connecting");
    const delay = backoffMs(this.attempt);
    this.attempt += 1;
    this.retryTimer = setTimeout(() => void this.connect(), delay);
  }
}
