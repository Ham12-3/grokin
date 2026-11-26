import { FolderOpen, Inbox, LogOut, Plus, Settings, Star, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Bot } from "@/features/bots/api";
import { StatusDot } from "@/features/bots/StatusDot";
import { cn } from "@/lib/utils";

interface SidebarProps {
  bots: Bot[];
  selectedId: string | null;
  isWorking: (bot: Bot) => boolean;
  /** Bots with something waiting for the user's approval. */
  waitingBotIds: Set<string>;
  pendingApprovals: number;
  approvalsOpen: boolean;
  onOpenApprovals: () => void;
  settingsOpen: boolean;
  onOpenSettings: () => void;
  groups: { id: string; title: string | null }[];
  selectedGroupId: string | null;
  onSelectGroup: (chatId: string) => void;
  onNewGroup: () => void;
  libraryOpen: boolean;
  onOpenLibrary: () => void;
  userLabel: string;
  onSelect: (botId: string) => void;
  onNewBot: () => void;
  onSignOut: () => void;
}

export function Sidebar({
  bots,
  selectedId,
  isWorking,
  waitingBotIds,
  pendingApprovals,
  approvalsOpen,
  onOpenApprovals,
  settingsOpen,
  onOpenSettings,
  groups,
  selectedGroupId,
  onSelectGroup,
  onNewGroup,
  libraryOpen,
  onOpenLibrary,
  userLabel,
  onSelect,
  onNewBot,
  onSignOut,
}: SidebarProps) {
  // A Bot is highlighted only while its own chat is what is on screen.
  const botSelected = !approvalsOpen && !settingsOpen && !libraryOpen && !selectedGroupId;
  return (
    <aside className="border-border bg-sidebar text-sidebar-foreground flex w-[260px] shrink-0 flex-col border-r">
      <div className="flex items-center justify-between px-4 py-3">
        <h1 className="text-sm font-semibold tracking-tight">Crew</h1>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="ghost" size="icon" aria-label="New">
                <Plus />
              </Button>
            }
          />
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onClick={onNewBot}>New Bot</DropdownMenuItem>
            <DropdownMenuItem onClick={onNewGroup}>New group chat</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="px-2 pb-2">
        <button
          type="button"
          aria-current={approvalsOpen ? "page" : undefined}
          onClick={onOpenApprovals}
          className={cn(
            "hover:bg-sidebar-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
            approvalsOpen && "bg-sidebar-accent font-medium",
          )}
        >
          <Inbox aria-hidden className="size-4" />
          <span className="flex-1">Approvals</span>
          {pendingApprovals > 0 && (
            <span
              aria-label={`${pendingApprovals} pending`}
              className="rounded-full bg-amber-500 px-1.5 text-xs font-medium text-white"
            >
              {pendingApprovals}
            </span>
          )}
        </button>
      </div>

      <nav aria-label="Bots" className="flex-1 overflow-y-auto px-2">
        <p className="text-muted-foreground px-2 py-1 text-xs font-medium tracking-wide uppercase">
          Bots
        </p>
        {bots.length === 0 && (
          <p className="text-muted-foreground px-2 py-2 text-xs">No Bots yet.</p>
        )}
        <ul className="space-y-0.5">
          {bots.map((bot) => (
            <li key={bot.id}>
              <button
                type="button"
                aria-current={bot.id === selectedId && botSelected ? "page" : undefined}
                onClick={() => onSelect(bot.id)}
                className={cn(
                  "hover:bg-sidebar-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                  bot.id === selectedId &&
                    !approvalsOpen &&
                    !settingsOpen &&
                    "bg-sidebar-accent font-medium",
                )}
              >
                <span aria-hidden>{bot.avatar ?? "🤖"}</span>
                <span className="min-w-0 flex-1 truncate">{bot.name}</span>
                {bot.is_primary && (
                  <Star aria-label="Primary Bot" className="size-3 fill-current text-amber-500" />
                )}
                <StatusDot working={isWorking(bot)} waiting={waitingBotIds.has(bot.id)} />
              </button>
            </li>
          ))}
        </ul>
        {groups.length > 0 && (
          <>
            <p className="text-muted-foreground px-2 pt-3 pb-1 text-xs font-medium tracking-wide uppercase">
              Groups
            </p>
            <ul aria-label="Groups" className="space-y-0.5">
              {groups.map((group) => (
                <li key={group.id}>
                  <button
                    type="button"
                    aria-current={group.id === selectedGroupId ? "page" : undefined}
                    onClick={() => onSelectGroup(group.id)}
                    className={cn(
                      "hover:bg-sidebar-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                      group.id === selectedGroupId && "bg-sidebar-accent font-medium",
                    )}
                  >
                    <Users aria-hidden className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{group.title ?? "Group chat"}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </nav>

      <div className="px-2 pb-1">
        <button
          type="button"
          aria-current={libraryOpen ? "page" : undefined}
          onClick={onOpenLibrary}
          className={cn(
            "hover:bg-sidebar-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
            libraryOpen && "bg-sidebar-accent font-medium",
          )}
        >
          <FolderOpen aria-hidden className="size-4" />
          Library
        </button>
      </div>

      <div className="border-border flex items-center gap-2 border-t px-3 py-2">
        <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs">{userLabel}</span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Settings"
          aria-pressed={settingsOpen}
          onClick={onOpenSettings}
        >
          <Settings />
        </Button>
        <Button variant="ghost" size="icon" aria-label="Sign out" onClick={onSignOut}>
          <LogOut />
        </Button>
      </div>
    </aside>
  );
}
