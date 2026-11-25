import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import * as tauri from "@/lib/tauri";

vi.mock("@/lib/tauri", () => ({ openExternal: vi.fn() }));

test("Enter sends and clears; Shift+Enter does not send", () => {
  const onSend = vi.fn();
  render(<Composer botName="Inbox Bot" busy={false} onSend={onSend} />);
  const box = screen.getByLabelText("Message Inbox Bot");

  fireEvent.change(box, { target: { value: "  hello  " } });
  fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
  expect(onSend).not.toHaveBeenCalled();

  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).toHaveBeenCalledWith("hello");
  expect(box).toHaveValue("");
});

test("nothing is sent while the Bot is replying or when the box is empty", () => {
  const onSend = vi.fn();
  const { rerender } = render(<Composer botName="Inbox Bot" busy onSend={onSend} />);
  const box = screen.getByLabelText("Message Inbox Bot");
  fireEvent.change(box, { target: { value: "hello" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  expect(box).toHaveValue("hello"); // the draft is kept

  rerender(<Composer botName="Inbox Bot" busy={false} onSend={onSend} />);
  fireEvent.change(box, { target: { value: "   " } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSend).not.toHaveBeenCalled();
});

test("while a run can be stopped, Stop replaces Send", () => {
  const onStop = vi.fn();
  const onSend = vi.fn();
  render(<Composer botName="Inbox Bot" busy onSend={onSend} onStop={onStop} />);
  expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(onStop).toHaveBeenCalledTimes(1);
  expect(onSend).not.toHaveBeenCalled();
});

test("markdown renders formatting", () => {
  render(<Markdown text={"**bold** and `code`\n\n- one\n- two"} />);
  expect(screen.getByText("bold").tagName).toBe("STRONG");
  expect(screen.getByText("code").tagName).toBe("CODE");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("markdown never renders raw HTML or script links from AI output", () => {
  const hostile =
    '<script>window.hacked = 1</script><img src="x" onerror="window.hacked = 1">' +
    "[click](javascript:window.hacked=1) <iframe src='https://evil.example'></iframe>";
  const { container } = render(<Markdown text={hostile} />);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("iframe")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("[onerror]")).toBeNull();
  for (const link of container.querySelectorAll("a")) {
    expect(link.getAttribute("href") ?? "").not.toMatch(/^javascript:/i);
  }
});

test("links open in the system browser, not in the app window", () => {
  render(<Markdown text="[docs](https://example.com/docs)" />);
  const link = screen.getByRole("link", { name: "docs" });
  const notCancelled = fireEvent.click(link);
  expect(notCancelled).toBe(false); // default navigation was prevented
  expect(tauri.openExternal).toHaveBeenCalledWith("https://example.com/docs");
});
