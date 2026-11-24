import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BotSettings } from "@/features/bots/BotSettings";
import type { Bot } from "@/features/bots/api";

// Empty for now; each fills in with its phase.
const LATER_TABS = [
  { value: "screen", label: "Screen", text: "The Bot's live screen appears here." },
  { value: "memory", label: "Memory", text: "What this Bot remembers about you." },
  { value: "skills", label: "Skills", text: "Saved procedures this Bot can run." },
  { value: "routines", label: "Routines", text: "Skills on a schedule or trigger." },
  { value: "apps", label: "Apps", text: "The apps this Bot may use." },
];

export function DetailsPane({ bot, onDeleted }: { bot: Bot; onDeleted: () => void }) {
  return (
    <aside
      aria-label="Details"
      className="border-border flex w-[360px] shrink-0 flex-col overflow-y-auto border-l p-3"
    >
      <Tabs defaultValue="settings">
        <TabsList className="flex w-full flex-wrap">
          {LATER_TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        {LATER_TABS.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <p className="text-muted-foreground p-4 text-center text-sm">
              {tab.text} Not available yet.
            </p>
          </TabsContent>
        ))}
        <TabsContent value="settings" className="pt-2">
          <BotSettings bot={bot} onDeleted={onDeleted} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
