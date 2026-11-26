import { useEffect, useState } from "react";
import type { LibraryDetail } from "./api";
import { Markdown } from "@/features/chat/Markdown";

type Loaded = { kind: "text"; text: string } | { kind: "blob"; url: string } | { kind: "none" };

const MAX_TEXT_CHARS = 200_000;

/**
 * Shows a Library file: markdown and text as text, images and PDFs from a local blob.
 * The file is fetched as data and never run: the server sends documents as plain text.
 */
export function Preview({ item }: { item: LibraryDetail }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stopped = false;
    let blobUrl: string | undefined;
    setLoaded(null);
    setFailed(false);
    void (async () => {
      try {
        if (item.category === "other") {
          setLoaded({ kind: "none" });
          return;
        }
        const response = await fetch(item.download_url);
        if (!response.ok) throw new Error("download failed");
        if (item.category === "document") {
          const text = (await response.text()).slice(0, MAX_TEXT_CHARS);
          if (!stopped) setLoaded({ kind: "text", text });
        } else {
          const bytes = await response.blob();
          // The stored type decides how it is shown, not what the file claims to be.
          blobUrl = URL.createObjectURL(new Blob([bytes], { type: item.mime ?? "" }));
          if (!stopped) setLoaded({ kind: "blob", url: blobUrl });
        }
      } catch {
        if (!stopped) setFailed(true);
      }
    })();
    return () => {
      stopped = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [item.id, item.download_url, item.category, item.mime]);

  if (failed) {
    return (
      <p role="alert" className="text-destructive text-sm">
        The preview could not be loaded. You can still save the file.
      </p>
    );
  }
  if (loaded === null) return <p className="text-muted-foreground text-sm">Loading preview...</p>;
  if (loaded.kind === "none") {
    return <p className="text-muted-foreground text-sm">No preview for this kind of file.</p>;
  }
  if (loaded.kind === "text") {
    return item.mime === "text/markdown" ? (
      <Markdown text={loaded.text} />
    ) : (
      <pre className="text-xs break-words whitespace-pre-wrap">{loaded.text}</pre>
    );
  }
  return item.category === "image" ? (
    <img src={loaded.url} alt={item.title} className="max-w-full rounded border" />
  ) : (
    <iframe src={loaded.url} title={item.title} className="h-[70vh] w-full rounded border" />
  );
}
