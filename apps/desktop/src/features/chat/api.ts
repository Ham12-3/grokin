import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Message = Schemas["MessageOut"];
export type MessagePage = Schemas["MessagePage"];
export type ToolCall = Schemas["ToolCallOut"];
export type Run = Schemas["RunOut"];
type MessagesData = InfiniteData<MessagePage, unknown>;

const PAGE_SIZE = 30;

export const messagesKey = (chatId: string) => ["messages", chatId] as const;

/** Pages are newest first; each further page holds older messages. */
export function useMessages(chatId: string) {
  return useInfiniteQuery({
    queryKey: messagesKey(chatId),
    queryFn: ({ pageParam }) => {
      const before = pageParam ? `&before=${pageParam}` : "";
      return apiFetch<MessagePage>(`/chats/${chatId}/messages?limit=${PAGE_SIZE}${before}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (oldest) => (oldest.has_more ? oldest.items[0]?.id : undefined),
  });
}

/** All loaded messages, oldest first. */
export function flattenMessages(data: MessagesData | undefined): Message[] {
  if (!data) return [];
  return [...data.pages].reverse().flatMap((page) => page.items);
}

export function findMessage(
  queryClient: QueryClient,
  chatId: string,
  messageId: string,
): Message | undefined {
  const data = queryClient.getQueryData<MessagesData>(messagesKey(chatId));
  return flattenMessages(data).find((message) => message.id === messageId);
}

/** Adds a message to the newest page, or replaces it if it is already loaded. */
export function upsertMessage(queryClient: QueryClient, message: Message): void {
  queryClient.setQueryData<MessagesData>(messagesKey(message.chat_id), (data) => {
    if (!data) return data;
    const known = data.pages.some((page) => page.items.some((item) => item.id === message.id));
    const pages = data.pages.map((page, index) => {
      if (known) {
        return {
          ...page,
          items: page.items.map((item) => (item.id === message.id ? message : item)),
        };
      }
      return index === 0 ? { ...page, items: [...page.items, message] } : page;
    });
    return { ...data, pages };
  });
}

export function setMessageContent(
  queryClient: QueryClient,
  chatId: string,
  messageId: string,
  content: string,
): void {
  const message = findMessage(queryClient, chatId, messageId);
  if (message) upsertMessage(queryClient, { ...message, content });
}

export function removeMessage(queryClient: QueryClient, chatId: string, messageId: string): void {
  queryClient.setQueryData<MessagesData>(messagesKey(chatId), (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.filter((item) => item.id !== messageId),
      })),
    };
  });
}

/** Tool steps of every loaded run, grouped by run id, oldest first. */
export function toolCallsByRun(data: MessagesData | undefined): Record<string, ToolCall[]> {
  const byRun: Record<string, ToolCall[]> = {};
  for (const page of [...(data?.pages ?? [])].reverse()) {
    for (const call of page.tool_calls) (byRun[call.run_id] ??= []).push(call);
  }
  return byRun;
}

/** Adds a tool step to the newest page, or replaces it if it is already loaded. */
export function upsertToolCall(queryClient: QueryClient, chatId: string, call: ToolCall): void {
  queryClient.setQueryData<MessagesData>(messagesKey(chatId), (data) => {
    if (!data) return data;
    const known = data.pages.some((page) => page.tool_calls.some((item) => item.id === call.id));
    const pages = data.pages.map((page, index) => {
      if (known) {
        return {
          ...page,
          tool_calls: page.tool_calls.map((item) => (item.id === call.id ? call : item)),
        };
      }
      return index === 0 ? { ...page, tool_calls: [...page.tool_calls, call] } : page;
    });
    return { ...data, pages };
  });
}

export function useRun(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => apiFetch<Run>("/runs/" + runId),
    enabled,
  });
}

export function cancelRun(runId: string) {
  return apiFetch<Schemas["CancelResponse"]>("/runs/" + runId + "/cancel", { method: "POST" });
}

export function useSendMessage(chatId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (message: { content: string; skillId?: string }) =>
      apiFetch<Schemas["SendMessageResponse"]>(`/chats/${chatId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: message.content, skill_id: message.skillId ?? null }),
      }),
    // The WebSocket also announces the message; upsert keeps a single copy.
    onSuccess: (sent) => upsertMessage(queryClient, sent.message),
  });
}
