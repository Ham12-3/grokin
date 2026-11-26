import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BotSettings } from "@/features/bots/BotSettings";
import type { Bot } from "@/features/bots/api";
import { ComputerStatus } from "@/features/computer/ComputerStatus";
import { useSendMessage } from "@/features/chat/api";
import { ScreenPanel } from "@/features/computer/ScreenPanel";
import { RoutinesTab } from "@/features/routines/RoutinesTab";
import { MemoryTab } from "@/features/memory/MemoryTab";
import { AppsTab } from "@/features/settings/AppsTab";
import { SkillsTab } from "@/features/skills/SkillsTab";

export type DetailsTab = "screen" | "memory" | "skills" | "routines" | "apps" | "settings";

interface DetailsPaneProps {
  bot: Bot;
  tab: DetailsTab;
  onTabChange: (tab: DetailsTab) => void;
  activeRunId: string | undefined;
  /** True while the Bot is busy: a skill cannot be started then. */
  working: boolean;
  interactive: boolean;
  onInteractiveChange: (interactive: boolean) => void;
  onDeleted: () => void;
  /** Opens the app's Settings (to connect more apps). */
  onOpenSettings: () => void;
}

export function DetailsPane({
  bot,
  tab,
  onTabChange,
  activeRunId,
  working,
  interactive,
  onInteractiveChange,
  onDeleted,
  onOpenSettings,
}: DetailsPaneProps) {
  const sendMessage = useSendMessage(bot.direct_chat_id ?? "");
  return (
    <aside
      aria-label="Details"
      className="border-border flex w-[360px] shrink-0 flex-col overflow-y-auto border-l p-3"
    >
      <Tabs value={tab} onValueChange={(value) => onTabChange(value as DetailsTab)}>
        <TabsList className="grid w-full grid-cols-3 gap-y-0.5 group-data-horizontal/tabs:h-auto">
          <TabsTrigger value="screen">Screen</TabsTrigger>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="skills">Skills</TabsTrigger>
          <TabsTrigger value="routines">Routines</TabsTrigger>
          <TabsTrigger value="apps">Apps</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="screen">
          {/* Mounted only while shown, so the live connection closes with the tab. */}
          {tab === "screen" && (
            <ScreenPanel
              bot={bot}
              activeRunId={activeRunId}
              interactive={interactive}
              onInteractiveChange={onInteractiveChange}
            />
          )}
        </TabsContent>
        <TabsContent value="memory">{tab === "memory" && <MemoryTab bot={bot} />}</TabsContent>
        <TabsContent value="skills">
          {tab === "skills" && (
            <SkillsTab
              bot={bot}
              canRun={!working && !sendMessage.isPending && Boolean(bot.direct_chat_id)}
              onRun={(skill) =>
                sendMessage.mutate({ content: `/${skill.slug}`, skillId: skill.id })
              }
            />
          )}
        </TabsContent>
        <TabsContent value="routines">
          {tab === "routines" && <RoutinesTab bot={bot} />}
        </TabsContent>
        <TabsContent value="apps">
          {tab === "apps" && <AppsTab bot={bot} onOpenSettings={onOpenSettings} />}
        </TabsContent>
        <TabsContent value="settings" className="space-y-6 pt-2">
          <BotSettings bot={bot} onDeleted={onDeleted} />
          <ComputerStatus onStopping={() => onInteractiveChange(false)} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
