/**
 * Live state from the WebSocket: connection status, text that is still streaming,
 * which Bots are working, and the last error per chat.
 */
import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";
import {
  findMessage,
  messagesKey,
  removeMessage,
  setMessageContent,
  upsertMessage,
  upsertToolCall,
  type Message,
  type ToolCall,
} from "@/features/chat/api";
import type { ServerEvent, WsStatus } from "@/lib/ws";

interface LiveStore {
  status: WsStatus;
  /** Text of messages that are streaming right now, by message id. */
  streaming: Record<string, string>;
  /** Live working state by Bot id. Missing means "use what the API said". */
  working: Record<string, boolean>;
  /** Last run error by chat id. */
  errors: Record<string, string>;
  /** The run in progress by chat id, so it can be stopped. */
  runs: Record<string, string>;
}

export const useLiveStore = create<LiveStore>(() => ({
  status: "connecting",
  streaming: {},
  working: {},
  errors: {},
  runs: {},
}));

const initialState = useLiveStore.getState();

export function resetLive(): void {
  useLiveStore.setState(initialState, true);
}

export function clearChatError(chatId: string): void {
  useLiveStore.setState((state) => {
    const errors = { ...state.errors };
    delete errors[chatId];
    return { errors };
  });
}

/**
 * Applies a streamed piece of text. Each delta says where it starts (`offset`).
 * Returns the new text, or null when a piece is missing and the chat must be refetched.
 */
export function applyDelta(current: string, offset: number, text: string): string | null {
  if (offset === current.length) return current + text;
  if (offset > current.length) return null; // we missed something
  const overlap = current.length - offset; // we already have the start of this piece
  return overlap >= text.length ? current : current + text.slice(overlap);
}

function setStreaming(messageId: string, text: string | undefined): void {
  useLiveStore.setState((state) => {
    const streaming = { ...state.streaming };
    if (text === undefined) delete streaming[messageId];
    else streaming[messageId] = text;
    return { streaming };
  });
}

const RESYNC_MS = 1000;
const lastResync = new Map<string, number>();

/** Refetches a chat, at most once a second, when a delta arrives out of order. */
function resync(queryClient: QueryClient, chatId: string, messageId: string): void {
  setStreaming(messageId, undefined);
  const now = Date.now();
  if (now - (lastResync.get(chatId) ?? 0) < RESYNC_MS) return;
  lastResync.set(chatId, now);
  void queryClient.invalidateQueries({ queryKey: messagesKey(chatId) });
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");

export function handleEvent(queryClient: QueryClient, event: ServerEvent): void {
  const chatId = str(event.chat_id);

  switch (event.type) {
    case "message.created": {
      const message = event.message as Message;
      upsertMessage(queryClient, message);
      if (message.role === "bot") setStreaming(message.id, message.content);
      break;
    }
    case "message.delta": {
      const messageId = str(event.message_id);
      const known =
        useLiveStore.getState().streaming[messageId] ??
        findMessage(queryClient, chatId, messageId)?.content;
      const next =
        known === undefined ? null : applyDelta(known, Number(event.offset), str(event.text));
      if (next === null) resync(queryClient, chatId, messageId);
      else setStreaming(messageId, next);
      break;
    }
    case "message.completed": {
      const messageId = str(event.message_id);
      const text = useLiveStore.getState().streaming[messageId];
      if (text !== undefined && text.length === Number(event.length)) {
        setMessageContent(queryClient, chatId, messageId, text);
        setStreaming(messageId, undefined);
      } else {
        lastResync.delete(chatId);
        resync(queryClient, chatId, messageId);
      }
      break;
    }
    case "tool.started":
    case "tool.finished":
      upsertToolCall(queryClient, chatId, event.tool_call as ToolCall);
      break;
    case "run.status": {
      const status = str(event.status);
      const botId = str(event.bot_id);
      const runId = str(event.run_id);
      const active = status === "queued" || status === "running";
      useLiveStore.setState((state) => {
        const runs = { ...state.runs };
        if (active) runs[chatId] = runId;
        else if (runs[chatId] === runId) delete runs[chatId];
        return { working: { ...state.working, [botId]: active }, runs };
      });
      if (status === "queued") clearChatError(chatId);
      if (!active) {
        void queryClient.invalidateQueries({ queryKey: ["me"] });
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
      }
      if (status === "failed" || status === "cancelled") {
        const messageId = str(event.message_id);
        const text = useLiveStore.getState().streaming[messageId];
        if (messageId && event.message_kept !== true) {
          removeMessage(queryClient, chatId, messageId);
        } else if (messageId && text !== undefined) {
          setMessageContent(queryClient, chatId, messageId, text);
        }
        if (messageId) setStreaming(messageId, undefined);
      }
      if (status === "failed") {
        const error = event.error as { message?: unknown } | undefined;
        const message = str(error?.message) || "Something went wrong while replying. Try again.";
        useLiveStore.setState((state) => ({ errors: { ...state.errors, [chatId]: message } }));
      }
      break;
    }
    default:
      break;
  }
}

/** After a reconnect: drop live text and refetch, so nothing is lost or doubled. */
export function handleReconnected(queryClient: QueryClient): void {
  useLiveStore.setState({ streaming: {}, working: {}, runs: {} });
  lastResync.clear();
  void queryClient.invalidateQueries({ queryKey: ["bots"] });
  void queryClient.invalidateQueries({ queryKey: ["messages"] });
}
