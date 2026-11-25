import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Skill = Schemas["SkillOut"];
export type SkillInput = Schemas["SkillCreate"];

export const skillsKey = (botId: string) => ["skills", botId] as const;

export function useSkills(botId: string) {
  return useQuery({
    queryKey: skillsKey(botId),
    queryFn: () => apiFetch<Skill[]>(`/bots/${botId}/skills`),
  });
}

export function useSkillActions(botId: string) {
  const queryClient = useQueryClient();
  const refresh = {
    onSettled: () => queryClient.invalidateQueries({ queryKey: skillsKey(botId) }),
  };
  const create = useMutation({
    mutationFn: (input: SkillInput) =>
      apiFetch<Skill>(`/bots/${botId}/skills`, { method: "POST", body: JSON.stringify(input) }),
    ...refresh,
  });
  const update = useMutation({
    mutationFn: (skill: { id: string; input: SkillInput }) =>
      apiFetch<Skill>(`/skills/${skill.id}`, {
        method: "PATCH",
        body: JSON.stringify(skill.input),
      }),
    ...refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/skills/${id}`, { method: "DELETE" }),
    ...refresh,
  });
  return { create, update, remove };
}

/** Save or cancel a skill the Bot drafted in the chat. */
export function answerSkillDraft(chatId: string, messageId: string, action: "save" | "cancel") {
  return apiFetch<Schemas["MessageOut"]>(`/chats/${chatId}/skill-drafts/${messageId}/${action}`, {
    method: "POST",
  });
}
