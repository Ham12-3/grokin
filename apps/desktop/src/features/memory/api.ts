import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type MemoryLine = Schemas["MemoryOut"];

export const memoryKey = (botId: string) => ["memory", botId] as const;

export function useMemory(botId: string) {
  return useQuery({
    queryKey: memoryKey(botId),
    queryFn: () => apiFetch<MemoryLine[]>(`/bots/${botId}/memory`),
  });
}

/** Add, edit and delete lines. Each refreshes the list. */
export function useMemoryActions(botId: string) {
  const queryClient = useQueryClient();
  const refresh = {
    onSettled: () => queryClient.invalidateQueries({ queryKey: memoryKey(botId) }),
  };
  const add = useMutation({
    mutationFn: (text: string) =>
      apiFetch<MemoryLine>(`/bots/${botId}/memory`, {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    ...refresh,
  });
  const edit = useMutation({
    mutationFn: (line: { id: string; text: string }) =>
      apiFetch<MemoryLine>(`/bots/${botId}/memory/${line.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text: line.text }),
      }),
    ...refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/bots/${botId}/memory/${id}`, { method: "DELETE" }),
    ...refresh,
  });
  return { add, edit, remove };
}
