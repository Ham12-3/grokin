import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Bot = Schemas["BotOut"];
export type BotInput = Schemas["BotCreate"];
export type ApprovalMode = Bot["approval_mode"];

export const botsKey = ["bots"] as const;

export function useBots() {
  return useQuery({ queryKey: botsKey, queryFn: () => apiFetch<Bot[]>("/bots") });
}

function useBotsMutation<TInput, TResult>(run: (input: TInput) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: botsKey }),
  });
}

export function useCreateBot() {
  return useBotsMutation((input: BotInput) =>
    apiFetch<Bot>("/bots", { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useUpdateBot(botId: string) {
  return useBotsMutation((input: Schemas["BotUpdate"]) =>
    apiFetch<Bot>(`/bots/${botId}`, { method: "PATCH", body: JSON.stringify(input) }),
  );
}

export function useDeleteBot(botId: string) {
  return useBotsMutation(() => apiFetch<void>(`/bots/${botId}`, { method: "DELETE" }));
}

export function useMakePrimary(botId: string) {
  return useBotsMutation(() => apiFetch<Bot>(`/bots/${botId}/primary`, { method: "POST" }));
}
