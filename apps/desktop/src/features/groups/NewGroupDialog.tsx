import { useState } from "react";
import { useGroupActions } from "./api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Bot } from "@/features/bots/api";
import { errorMessage } from "@/lib/tauri";

interface NewGroupDialogProps {
  bots: Bot[];
  onClose: () => void;
  onCreated: (chatId: string) => void;
}

/** Pick 2 to 6 Bots for a group chat. */
export function NewGroupDialog({ bots, onClose, onCreated }: NewGroupDialogProps) {
  const { create } = useGroupActions();
  const [picked, setPicked] = useState<string[]>([]);
  const valid = picked.length >= 2 && picked.length <= 6;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New group chat</DialogTitle>
          <DialogDescription>
            Pick 2 to 6 Bots. Mention one with @ to ask it directly.
          </DialogDescription>
        </DialogHeader>
        {bots.length < 2 ? (
          <p className="text-sm">You need at least two Bots for a group chat.</p>
        ) : (
          <ul aria-label="Bots" className="space-y-1">
            {bots.map((bot) => (
              <li key={bot.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={picked.includes(bot.id)}
                    onChange={(event) =>
                      setPicked((current) =>
                        event.target.checked
                          ? [...current, bot.id]
                          : current.filter((id) => id !== bot.id),
                      )
                    }
                  />
                  <span aria-hidden>{bot.avatar ?? "🤖"}</span>
                  {bot.name}
                </label>
              </li>
            ))}
          </ul>
        )}
        {create.isError && (
          <p role="alert" className="text-destructive text-xs">
            {errorMessage(create.error)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!valid || create.isPending}
            onClick={() => create.mutate(picked, { onSuccess: (chat) => onCreated(chat.id) })}
          >
            Create group
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
