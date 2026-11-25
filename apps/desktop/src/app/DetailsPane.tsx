import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BotSettings } from "@/features/bots/BotSettings";
import type { Bot } from "@/features/bots/api";
import { ComputerStatus } from "@/features/computer/ComputerStatus";
import { ScreenPanel } from "@/features/computer/ScreenPanel";

// Empty for now; each fills in with its phase.
const LATER_TABS = [
  { value: "memory", label: "Memory", text: "What this Bot remembers about you." },
  { value: "skills", label: "Skills", text: "Saved procedures this Bot can run." },
  { value: "routines", label: "Routines", text: "Skills on a schedule or trigger." },
  { value: "apps", label: "Apps", text: "The apps this Bot may use." },
];

export type DetailsTab = "screen" | "memory" | "skills" | "routines" | "apps" | "settings";

interface DetailsPaneProps {
  bot: Bot;
  tab: DetailsTab;
  onTabChange: (tab: DetailsTab) => void;
  activeRunId: string | undefined;
  interactive: boolean;
  onInteractiveChange: (interactive: boolean) => void;
  onDeleted: () => void;
}

export function DetailsPane({
  bot,
  tab,
  onTabChange,
  activeRunId,
  interactive,
  onInteractiveChange,
  onDeleted,
}: DetailsPaneProps) {
  return (
    <aside
      aria-label="Details"
      className="border-border flex w-[360px] shrink-0 flex-col overflow-y-auto border-l p-3"
    >
      <Tabs value={tab} onValueChange={(value) => onTabChange(value as DetailsTab)}>
        <TabsList className="flex h-auto w-full flex-wrap">
          <TabsTrigger value="screen">Screen</TabsTrigger>
          {LATER_TABS.map((item) => (
            <TabsTrigger key={item.value} value={item.value}>
              {item.label}
            </TabsTrigger>
          ))}
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
        {LATER_TABS.map((item) => (
          <TabsContent key={item.value} value={item.value}>
            <p className="text-muted-foreground p-4 text-center text-sm">
              {item.text} Not available yet.
            </p>
          </TabsContent>
        ))}
        <TabsContent value="settings" className="space-y-6 pt-2">
          <BotSettings bot={bot} onDeleted={onDeleted} />
          <ComputerStatus onStopping={() => onInteractiveChange(false)} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
