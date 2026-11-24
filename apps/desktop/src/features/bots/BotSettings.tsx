import { useState } from "react";
import { BotForm } from "./BotForm";
import { useDeleteBot, useMakePrimary, useUpdateBot, type Bot } from "./api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/tauri";

export function BotSettings({ bot, onDeleted }: { bot: Bot; onDeleted: () => void }) {
  const updateBot = useUpdateBot(bot.id);
  const deleteBot = useDeleteBot(bot.id);
  const makePrimary = useMakePrimary(bot.id);
  const [confirming, setConfirming] = useState(false);
  const [saved, setSaved] = useState(false);

  const failed = updateBot.error ?? deleteBot.error ?? makePrimary.error;

  return (
    <div className="space-y-4">
      <BotForm
        key={bot.id}
        initial={{
          name: bot.name,
          avatar: bot.avatar,
          job: bot.job,
          instructions: bot.instructions,
          approval_mode: bot.approval_mode,
        }}
        submitLabel="Save"
        busy={updateBot.isPending}
        error={failed ? errorMessage(failed) : null}
        onSubmit={(changes) => {
          setSaved(false);
          updateBot.mutate(changes, { onSuccess: () => setSaved(true) });
        }}
        extraActions={
          <Button type="button" variant="destructive" onClick={() => setConfirming(true)}>
            Delete Bot
          </Button>
        }
      />
      {saved && (
        <p role="status" className="text-muted-foreground text-xs">
          Saved.
        </p>
      )}

      {!bot.is_primary && (
        <Button
          type="button"
          variant="outline"
          className="w-full"
          disabled={makePrimary.isPending}
          onClick={() => makePrimary.mutate()}
        >
          Make Primary Bot
        </Button>
      )}

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {bot.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This also deletes its chat history. It cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteBot.isPending}
              onClick={() =>
                deleteBot.mutate(undefined, {
                  onSuccess: () => {
                    setConfirming(false);
                    onDeleted();
                  },
                })
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
