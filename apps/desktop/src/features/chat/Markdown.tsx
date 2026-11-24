import type { MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { openExternal } from "@/lib/tauri";

function openLink(event: MouseEvent<HTMLAnchorElement>) {
  // Never navigate the app window: links open in the system browser.
  event.preventDefault();
  void openExternal(event.currentTarget.href);
}

/** Renders AI output. Always sanitized; raw HTML in the text is never trusted. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown text-sm leading-relaxed break-words">
      <ReactMarkdown
        rehypePlugins={[rehypeSanitize]}
        components={{
          a: ({ href, children }) => (
            <a href={href} onClick={openLink} className="underline underline-offset-2">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
