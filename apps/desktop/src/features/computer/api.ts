import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Computer = Schemas["ComputerOut"];
export type ComputerStatus = Computer["status"];

export const computerKey = ["computer"] as const;

export function useComputer() {
  return useQuery({ queryKey: computerKey, queryFn: () => apiFetch<Computer>("/computer") });
}

function useComputerAction(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<Computer>(path, { method: "POST" }),
    onSuccess: (computer) => queryClient.setQueryData(computerKey, computer),
    onError: () => queryClient.invalidateQueries({ queryKey: computerKey }),
  });
}

export const useStartComputer = () => useComputerAction("/computer/start");
export const useStopComputer = () => useComputerAction("/computer/stop");

export function pauseRun(runId: string) {
  return apiFetch<Schemas["CancelResponse"]>("/runs/" + runId + "/pause", { method: "POST" });
}

export function resumeRun(runId: string) {
  return apiFetch<Schemas["CancelResponse"]>("/runs/" + runId + "/resume", { method: "POST" });
}

/** The live screen of a Bot's display. The token goes in a subprotocol, not the URL. */
export function screenUrl(apiBase: string, computerId: string, botId: string): string {
  const base = apiBase.replace(/^http/, "ws");
  return base + "/api/v1/computer/" + computerId + "/vnc?bot_id=" + botId;
}
