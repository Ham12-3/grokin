import { LayoutGrid, List } from "lucide-react";
import { useState } from "react";
import { Preview } from "./Preview";
import {
  formatSize,
  useDeleteLibraryItem,
  useLibrary,
  useLibraryItem,
  type Category,
  type LibraryItem,
} from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Bot } from "@/features/bots/api";
import { errorMessage, saveFile } from "@/lib/tauri";
import { cn } from "@/lib/utils";

const ICON: Record<Category, string> = { document: "📄", image: "🖼️", pdf: "📕", other: "📦" };
const SELECT = "border-input bg-background h-9 rounded-md border px-2 text-sm";

interface LibraryScreenProps {
  bots: Bot[];
  /** The item to show (from a file card in a chat). */
  selectedId: string | null;
  onSelect: (itemId: string | null) => void;
}

/** Everything your Bots made for you to keep: search, preview and save. */
export function LibraryScreen({ bots, selectedId, onSelect }: LibraryScreenProps) {
  const [q, setQ] = useState("");
  const [botId, setBotId] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const items = useLibrary({ q, botId, category });
  const detail = useLibraryItem(selectedId);
  const remove = useDeleteLibraryItem();
  const [saved, setSaved] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const botName = (id: string | null) => bots.find((bot) => bot.id === id)?.name ?? "";

  async function save() {
    if (!detail.data) return;
    setSaved(null);
    setSaveError(null);
    try {
      const name = detail.data.path?.split("/").pop() ?? detail.data.title;
      const done = await saveFile(detail.data.download_url, name);
      if (done) setSaved("Saved to your computer.");
    } catch (caught) {
      setSaveError(errorMessage(caught, "The file could not be saved."));
    }
  }

  const entry = (item: LibraryItem) => (
    <li key={item.id}>
      <button
        type="button"
        aria-current={item.id === selectedId ? "true" : undefined}
        onClick={() => {
          setSaved(null);
          onSelect(item.id);
        }}
        className={cn(
          "hover:bg-muted w-full rounded-md border text-left",
          view === "grid" ? "space-y-1 p-3" : "flex items-center gap-2 px-3 py-2",
          item.id === selectedId && "bg-muted",
        )}
      >
        <span aria-hidden className={view === "grid" ? "block text-2xl" : ""}>
          {ICON[item.category]}
        </span>
        <span className="block min-w-0 flex-1 truncate text-sm font-medium">{item.title}</span>
        <span className="text-muted-foreground block truncate text-xs">
          {[botName(item.bot_id), formatSize(item.size_bytes)].filter(Boolean).join(" · ")}
        </span>
      </button>
    </li>
  );

  return (
    <section aria-label="Library" className="flex min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-border space-y-2 border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Library</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              aria-label="Search the Library"
              placeholder="Search"
              className="max-w-xs"
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
            <select
              aria-label="Filter by Bot"
              className={SELECT}
              value={botId}
              onChange={(event) => setBotId(event.target.value)}
            >
              <option value="">All Bots</option>
              {bots.map((bot) => (
                <option key={bot.id} value={bot.id}>
                  {bot.name}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by type"
              className={SELECT}
              value={category}
              onChange={(event) => setCategory(event.target.value as Category | "")}
            >
              <option value="">All types</option>
              <option value="document">Documents</option>
              <option value="image">Images</option>
              <option value="pdf">PDFs</option>
              <option value="other">Other</option>
            </select>
            <Button
              variant="ghost"
              size="icon"
              aria-label={view === "grid" ? "Show as a list" : "Show as a grid"}
              onClick={() => setView(view === "grid" ? "list" : "grid")}
            >
              {view === "grid" ? <List /> : <LayoutGrid />}
            </Button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          {items.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
          {items.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(items.error, "Could not load the Library.")}
            </p>
          )}
          {items.isSuccess && items.data.length === 0 && (
            <p className="text-muted-foreground text-sm">
              {q || botId || category
                ? "Nothing matches."
                : "Nothing here yet. Files your Bots save for you appear here."}
            </p>
          )}
          <ul
            aria-label="Library items"
            className={
              view === "grid"
                ? "grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-2"
                : "space-y-1"
            }
          >
            {items.data?.map(entry)}
          </ul>
        </div>
      </div>
      {selectedId && (
        <aside
          aria-label="Preview"
          className="border-border flex w-[420px] shrink-0 flex-col gap-3 overflow-y-auto border-l p-4"
        >
          {detail.isPending && <p className="text-muted-foreground text-sm">Loading...</p>}
          {detail.isError && (
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(detail.error, "This item could not be opened.")}
            </p>
          )}
          {detail.data && (
            <>
              <header>
                <h3 className="text-sm font-semibold break-words">{detail.data.title}</h3>
                <p className="text-muted-foreground text-xs break-all">
                  {[
                    botName(detail.data.bot_id),
                    formatSize(detail.data.size_bytes),
                    detail.data.path,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </header>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => void save()}>
                  Save to computer
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(detail.data.id, { onSuccess: () => onSelect(null) })}
                >
                  Remove
                </Button>
                <Button size="sm" variant="outline" onClick={() => onSelect(null)}>
                  Close
                </Button>
              </div>
              {saved && (
                <p role="status" className="text-muted-foreground text-xs">
                  {saved}
                </p>
              )}
              {saveError && (
                <p role="alert" className="text-destructive text-xs">
                  {saveError}
                </p>
              )}
              <Preview item={detail.data} />
            </>
          )}
        </aside>
      )}
    </section>
  );
}
