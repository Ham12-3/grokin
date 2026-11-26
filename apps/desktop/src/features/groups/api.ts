import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Chat = Schemas["ChatOut"];

export const chatsKey = ["chats"] as const;

/** The user's group chats (each Bot's own chat comes with the Bot). */
export function useGroups() {
  return useQuery({
    queryKey: chatsKey,
    queryFn: () => apiFetch<Chat[]>("/chats"),
    select: (chats) => chats.filter((chat) => chat.kind === "group"),
  });
}

export function useGroupActions() {
  const queryClient = useQueryClient();
  const refresh = { onSettled: () => queryClient.invalidateQueries({ queryKey: chatsKey }) };
  return {
    create: useMutation({
      mutationFn: (botIds: string[]) =>
        apiFetch<Chat>("/chats", { method: "POST", body: JSON.stringify({ bot_ids: botIds }) }),
      ...refresh,
    }),
    remove: useMutation({
      mutationFn: (chatId: string) => apiFetch<void>(`/chats/${chatId}`, { method: "DELETE" }),
      ...refresh,
    }),
  };
}
