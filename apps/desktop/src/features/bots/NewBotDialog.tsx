import { BotForm } from "./BotForm";
import { useCreateBot } from "./api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorMessage } from "@/lib/tauri";

interface NewBotDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (botId: string) => void;
}

export function NewBotDialog({ open, onOpenChange, onCreated }: NewBotDialogProps) {
  const createBot = useCreateBot();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New Bot</DialogTitle>
          <DialogDescription>A teammate with one narrow job.</DialogDescription>
        </DialogHeader>
        {open && (
          <BotForm
            submitLabel="Create Bot"
            busy={createBot.isPending}
            error={createBot.isError ? errorMessage(createBot.error) : null}
            onSubmit={(bot) =>
              createBot.mutate(bot, {
                onSuccess: (created) => {
                  onOpenChange(false);
                  onCreated(created.id);
                },
              })
            }
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
