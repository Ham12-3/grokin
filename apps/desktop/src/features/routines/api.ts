import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Routine = Schemas["RoutineOut"];
export type RoutineRun = Schemas["RoutineRunOut"];
export type RoutineInput = Schemas["RoutineCreate"];
export type Trigger = Routine["trigger"];

export const routinesKey = (botId: string) => ["routines", botId] as const;
export const routineRunsKey = (routineId: string) => ["routine-runs", routineId] as const;

export function useRoutines(botId: string) {
  return useQuery({
    queryKey: routinesKey(botId),
    queryFn: () => apiFetch<Routine[]>(`/bots/${botId}/routines`),
  });
}

export function useRoutineRuns(routineId: string, enabled: boolean) {
  return useQuery({
    queryKey: routineRunsKey(routineId),
    queryFn: () => apiFetch<RoutineRun[]>(`/routines/${routineId}/runs`),
    enabled,
  });
}

/** The next times a schedule would run. Empty while the schedule is not valid. */
export function useCronPreview(cron: string, timezone: string, enabled: boolean) {
  return useQuery({
    queryKey: ["cron-preview", cron, timezone],
    queryFn: () =>
      apiFetch<Schemas["CronPreview"]>("/routines/preview", {
        method: "POST",
        body: JSON.stringify({ cron, timezone }),
      }),
    enabled: enabled && cron.trim().length > 0,
    retry: false,
  });
}

export function useRoutineActions(botId: string) {
  const queryClient = useQueryClient();
  const refresh = {
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: routinesKey(botId) });
      void queryClient.invalidateQueries({ queryKey: ["routine-runs"] });
    },
  };
  const post = (path: string) => apiFetch<unknown>(path, { method: "POST" });
  return {
    create: useMutation({
      mutationFn: (input: RoutineInput) =>
        apiFetch<Routine>(`/bots/${botId}/routines`, {
          method: "POST",
          body: JSON.stringify(input),
        }),
      ...refresh,
    }),
    setPaused: useMutation({
      mutationFn: (routine: { id: string; paused: boolean }) =>
        post(`/routines/${routine.id}/${routine.paused ? "pause" : "resume"}`),
      ...refresh,
    }),
    test: useMutation({ mutationFn: (id: string) => post(`/routines/${id}/test`), ...refresh }),
    remove: useMutation({
      mutationFn: (id: string) => apiFetch<void>(`/routines/${id}`, { method: "DELETE" }),
      ...refresh,
    }),
  };
}

export function pauseAllRoutines() {
  return apiFetch<Schemas["PauseAllResponse"]>("/routines/pause-all", { method: "POST" });
}

const pad = (value: string) => value.padStart(2, "0");

/** A schedule in plain words. Unusual cron expressions are shown as they are. */
export function describeTrigger(trigger: Trigger): string {
  if (trigger.type === "webhook") return "When its webhook is called";
  if (trigger.type === "connector_event") return `On ${trigger.connector}: ${trigger.event}`;
  const [minute, hour, day, month, weekday] = trigger.cron.split(/\s+/);
  const numbers = /^\d+$/.test(minute) && /^\d+$/.test(hour);
  // Say the zone only when it is not the one this computer is in.
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zone = trigger.timezone === here ? "" : ` ${trigger.timezone}`;
  if (numbers && day === "*" && month === "*") {
    const time = `${pad(hour)}:${pad(minute)}${zone}`;
    if (weekday === "*") return `Every day at ${time}`;
    if (weekday === "1-5") return `Every weekday at ${time}`;
  }
  if (/^\d+$/.test(minute) && hour === "*" && day === "*" && month === "*" && weekday === "*") {
    return minute === "0" ? "Every hour" : `Every hour at :${pad(minute)}`;
  }
  return `Custom schedule (${trigger.cron})`;
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
