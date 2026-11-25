import { ApprovalCard } from "./ApprovalCard";
import { useApprovals, type Approval } from "./api";
import { Button } from "@/components/ui/button";
import type { Bot } from "@/features/bots/api";
import { errorMessage } from "@/lib/tauri";

interface ApprovalsScreenProps {
  bots: Bot[];
  onOpenBot: (botId: string) => void;
}

/** Everything waiting for the user across all Bots, grouped by Bot. */
export function ApprovalsScreen({ bots, onOpenBot }: ApprovalsScreenProps) {
  const approvals = useApprovals();
  const groups = new Map<string, Approval[]>();
  for (const approval of approvals.data ?? []) {
    groups.set(approval.bot_id, [...(groups.get(approval.bot_id) ?? []), approval]);
  }

  return (
    <section aria-label="Approvals" className="min-w-0 flex-1 overflow-y-auto">
      <header className="border-border border-b px-4 py-3">
        <h2 className="text-sm font-semibold">Approvals</h2>
        <p className="text-muted-foreground text-xs">
          Your Bots wait here before they send, post, buy, delete or share anything.
        </p>
      </header>
      <div className="mx-auto max-w-2xl space-y-6 p-4">
        {approvals.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
        {approvals.isError && (
          <div className="space-y-3">
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(approvals.error, "Could not load approvals.")}
            </p>
            <Button variant="outline" onClick={() => void approvals.refetch()}>
              Retry
            </Button>
          </div>
        )}
        {approvals.isSuccess && groups.size === 0 && (
          <p className="text-muted-foreground text-sm">Nothing is waiting for you.</p>
        )}
        {[...groups].map(([botId, items]) => {
          const bot = bots.find((item) => item.id === botId);
          const name = bot?.name ?? "A Bot";
          return (
            <section key={botId} aria-label={name} className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-medium">
                <span aria-hidden>{bot?.avatar ?? "🤖"}</span>
                {name}
                {bot && (
                  <button
                    type="button"
                    className="text-muted-foreground text-xs font-normal underline"
                    onClick={() => onOpenBot(bot.id)}
                  >
                    Open chat
                  </button>
                )}
              </h3>
              {items.map((approval) => (
                <ApprovalCard key={approval.id} approval={approval} botName={name} />
              ))}
            </section>
          );
        })}
      </div>
    </section>
  );
}
