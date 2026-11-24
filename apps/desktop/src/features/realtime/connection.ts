import type { QueryClient } from "@tanstack/react-query";
import { handleEvent, handleReconnected, resetLive, useLiveStore } from "./live";
import { apiBaseUrl, authGetAccessToken } from "@/lib/tauri";
import { WsClient, wsUrl } from "@/lib/ws";

let client: WsClient | null = null;
/** Chats the UI wants, kept here because a chat can mount before the socket starts. */
const wanted = new Set<string>();

/** Opens the app's one WebSocket. Returns a function that closes it. */
export function startRealtime(queryClient: QueryClient): () => void {
  const ws = new WsClient({
    getUrl: async () => wsUrl(await apiBaseUrl()),
    getToken: (force) => authGetAccessToken(force),
    onEvent: (event) => handleEvent(queryClient, event),
    onStatus: (status) => useLiveStore.setState({ status }),
    onReconnected: () => handleReconnected(queryClient),
  });
  client = ws;
  for (const chatId of wanted) ws.subscribe(chatId);
  ws.start();
  return () => {
    ws.stop();
    if (client === ws) client = null;
    resetLive();
  };
}

export function subscribeChat(chatId: string): () => void {
  wanted.add(chatId);
  client?.subscribe(chatId);
  return () => {
    wanted.delete(chatId);
    client?.unsubscribe(chatId);
  };
}
