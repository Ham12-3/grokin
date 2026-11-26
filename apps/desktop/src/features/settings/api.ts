import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type VaultItem = Schemas["VaultItemOut"];
export type VaultType = VaultItem["type"];
export type Connector = Schemas["ConnectorOut"];
export type ConnectorList = Schemas["ConnectorList"];

export const vaultKey = ["vault"] as const;
export const connectorsKey = ["connectors"] as const;
export const botAppsKey = (botId: string) => ["bot-apps", botId] as const;

export function useVault() {
  return useQuery({ queryKey: vaultKey, queryFn: () => apiFetch<VaultItem[]>("/vault") });
}

export function useVaultActions() {
  const queryClient = useQueryClient();
  const refresh = { onSettled: () => queryClient.invalidateQueries({ queryKey: vaultKey }) };
  return {
    add: useMutation({
      // The value is sent once and never comes back.
      mutationFn: (item: { name: string; type: VaultType; value: string }) =>
        apiFetch<VaultItem>("/vault", { method: "POST", body: JSON.stringify(item) }),
      ...refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => apiFetch<void>(`/vault/${id}`, { method: "DELETE" }),
      ...refresh,
    }),
  };
}

export function useConnectors() {
  return useQuery({
    queryKey: connectorsKey,
    queryFn: () => apiFetch<ConnectorList>("/connectors"),
  });
}

export function useConnectorActions() {
  const queryClient = useQueryClient();
  const refresh = {
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: connectorsKey });
      void queryClient.invalidateQueries({ queryKey: ["bot-apps"] });
    },
  };
  return {
    connect: useMutation({
      mutationFn: (kind: string) =>
        apiFetch<Schemas["ConnectStarted"]>(`/connectors/${kind}/connect`, { method: "POST" }),
      ...refresh,
    }),
    addMcp: useMutation({
      mutationFn: (server: Schemas["McpCreate"]) =>
        apiFetch<Connector>("/connectors/mcp", { method: "POST", body: JSON.stringify(server) }),
      ...refresh,
    }),
    setSafeTools: useMutation({
      mutationFn: (change: { id: string; safeTools: string[] }) =>
        apiFetch<Connector>(`/connectors/${change.id}`, {
          method: "PATCH",
          body: JSON.stringify({ safe_tools: change.safeTools }),
        }),
      ...refresh,
    }),
    disconnect: useMutation({
      mutationFn: (id: string) => apiFetch<void>(`/connectors/${id}`, { method: "DELETE" }),
      ...refresh,
    }),
  };
}

export function useBotApps(botId: string) {
  return useQuery({
    queryKey: botAppsKey(botId),
    queryFn: () => apiFetch<Schemas["BotApps"]>(`/bots/${botId}/apps`),
  });
}

export function useSetBotApps(botId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (connectorIds: string[]) =>
      apiFetch<Schemas["BotApps"]>(`/bots/${botId}/apps`, {
        method: "PUT",
        body: JSON.stringify({ connector_ids: connectorIds }),
      }),
    onSuccess: (apps) => queryClient.setQueryData(botAppsKey(botId), apps),
    onError: () => queryClient.invalidateQueries({ queryKey: botAppsKey(botId) }),
  });
}
