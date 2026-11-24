import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { backoffMs, WsClient, wsUrl, type ServerEvent, type WsStatus } from "./ws";

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState: number = WebSocket.CONNECTING;
  sent: Record<string, string>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, string>);
  }
  close() {
    this.readyState = WebSocket.CLOSED;
  }
  open() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }
  drop(code = 1006) {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

function setup() {
  const statuses: WsStatus[] = [];
  const events: ServerEvent[] = [];
  const getToken = vi.fn(async (force: boolean) => (force ? "fresh" : "token"));
  const onReconnected = vi.fn();
  const client = new WsClient({
    getUrl: async () => "ws://api.test/api/v1/ws",
    getToken,
    onEvent: (event) => events.push(event),
    onStatus: (status) => statuses.push(status),
    onReconnected,
    createSocket: (url, protocols) => new FakeSocket(url, protocols) as unknown as WebSocket,
  });
  return { client, statuses, events, getToken, onReconnected };
}

const latest = () => FakeSocket.instances[FakeSocket.instances.length - 1];
const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.instances = [];
});
afterEach(() => vi.useRealTimers());

test("backoff doubles from 1s and stops at 30s", () => {
  expect([0, 1, 2, 3, 4, 5, 6].map(backoffMs)).toEqual([
    1000, 2000, 4000, 8000, 16000, 30000, 30000,
  ]);
});

test("wsUrl switches the scheme", () => {
  expect(wsUrl("http://localhost:8000")).toBe("ws://localhost:8000/api/v1/ws");
  expect(wsUrl("https://api.crew.local")).toBe("wss://api.crew.local/api/v1/ws");
});

test("sends the token as a subprotocol, never in the URL", async () => {
  const { client } = setup();
  client.start();
  await flush();
  expect(latest().url).toBe("ws://api.test/api/v1/ws");
  expect(latest().protocols).toEqual(["crew.v1", "bearer.token"]);
});

test("subscribes on open and forwards events", async () => {
  const { client, events, statuses } = setup();
  client.subscribe("chat-1");
  client.start();
  await flush();
  expect(latest().sent).toEqual([]); // not open yet
  latest().open();
  expect(latest().sent).toEqual([{ type: "subscribe", chat_id: "chat-1" }]);
  expect(statuses).toEqual(["connecting", "open"]);

  latest().onmessage?.({ data: JSON.stringify({ type: "pong" }) });
  latest().onmessage?.({ data: "not json" });
  expect(events).toEqual([{ type: "pong" }]);
});

test("reconnects with backoff, re-subscribes and reports the reconnect", async () => {
  const { client, statuses, onReconnected } = setup();
  client.subscribe("chat-1");
  client.start();
  await flush();
  latest().open();

  latest().drop();
  expect(statuses[statuses.length - 1]).toBe("reconnecting");
  await vi.advanceTimersByTimeAsync(999);
  expect(FakeSocket.instances).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(FakeSocket.instances).toHaveLength(2);

  // Still down: the next try waits 2s.
  latest().drop();
  await vi.advanceTimersByTimeAsync(1999);
  expect(FakeSocket.instances).toHaveLength(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(FakeSocket.instances).toHaveLength(3);

  expect(onReconnected).not.toHaveBeenCalled();
  latest().open();
  expect(onReconnected).toHaveBeenCalledTimes(1);
  expect(latest().sent).toEqual([{ type: "subscribe", chat_id: "chat-1" }]);
  expect(statuses[statuses.length - 1]).toBe("open");
});

test("asks for a fresh token after the server closes for an expired one", async () => {
  const { client, getToken } = setup();
  client.start();
  await flush();
  latest().open();
  latest().drop(4401);
  await vi.advanceTimersByTimeAsync(1000);
  expect(getToken).toHaveBeenLastCalledWith(true);
  expect(latest().protocols).toEqual(["crew.v1", "bearer.fresh"]);
});

test("keeps retrying when the token cannot be fetched", async () => {
  const { client, getToken } = setup();
  getToken.mockRejectedValueOnce(new Error("offline"));
  client.start();
  await flush();
  expect(FakeSocket.instances).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(1000);
  expect(FakeSocket.instances).toHaveLength(1);
});

test("stop closes the socket and does not reconnect", async () => {
  const { client, statuses } = setup();
  client.start();
  await flush();
  latest().open();
  client.stop();
  latest().drop();
  await vi.advanceTimersByTimeAsync(60_000);
  expect(FakeSocket.instances).toHaveLength(1);
  expect(statuses[statuses.length - 1]).toBe("closed");
});

test("unsubscribed chats are not re-subscribed", async () => {
  const { client } = setup();
  client.start();
  await flush();
  latest().open();
  client.subscribe("chat-1");
  client.unsubscribe("chat-1");
  latest().drop();
  await vi.advanceTimersByTimeAsync(1000);
  latest().open();
  expect(latest().sent).toEqual([]);
});
