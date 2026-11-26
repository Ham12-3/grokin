import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type LibraryItem = Schemas["LibraryItemOut"];
export type LibraryDetail = Schemas["LibraryItemDetail"];
export type Category = LibraryItem["category"];

export interface LibraryFilters {
  q: string;
  botId: string;
  category: Category | "";
}

export function useLibrary(filters: LibraryFilters) {
  return useQuery({
    queryKey: ["library", filters],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filters.q.trim()) params.set("q", filters.q.trim());
      if (filters.botId) params.set("bot_id", filters.botId);
      if (filters.category) params.set("category", filters.category);
      const query = params.toString();
      return apiFetch<LibraryItem[]>("/library" + (query ? `?${query}` : ""));
    },
  });
}

/** One item with a download address that works for a few minutes. */
export function useLibraryItem(itemId: string | null) {
  return useQuery({
    queryKey: ["library-item", itemId],
    queryFn: () => apiFetch<LibraryDetail>(`/library/${itemId}`),
    enabled: itemId !== null,
    staleTime: 60_000, // well inside the link's life
  });
}

export function useDeleteLibraryItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/library/${id}`, { method: "DELETE" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["library"] }),
  });
}

export function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
