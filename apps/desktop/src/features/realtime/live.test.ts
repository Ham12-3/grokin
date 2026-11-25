import { QueryClient, type InfiniteData } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import {
  applyDelta,
  dropChatStreaming,
  handleEvent,
  handleReconnected,
  resetLive,
  useLiveStore,
} from "./live";
import { approvalsKey, type Approval } from "@/features/approvals/api";
import {
  flattenMessages,
  messagesKey,
  toolCallsByRun,
  type Message,
  type MessagePage,
} from "@/features/chat/api";
import * as tauri from "@/lib/tauri";

vi.mock("@/lib/tauri", async (importOriginal) => ({
  ...(await importOriginal<typeof tauri>()),
  notify: vi.fn(() => Promise.resolve(true)),
}));

const CHAT = "chat-1";
const BOT = "bot-1";

function message(id: string, role: Message["role"], content: string): Message {
  return {
    id,
    chat_id: CHAT,
    role,
    bot_id: role === "bot" ? BOT : null,
    content,
    run_id: "run-1",
    created_at: "2026-01-01T00:00:00Z",
  };
}

function seeded(items: Message[]): QueryClient {
  // No garbage-collection timers: nothing mounts these queries.
  const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  queryClient.setQueryData<InfiniteData<MessagePage, unknown>>(messagesKey(CHAT), {
    pages: [{ items, has_more: false, active_run_id: null, tool_calls: [] }],
    pageParams: [undefined],
  });
  return queryClient;
}

const contents = (queryClient: QueryClient) =>
  flattenMessages(queryClient.getQueryData(messagesKey(CHAT))).map((item) => item.content);

const delta = (offset: number, text: string) => ({
  type: "message.delta",
  chat_id: CHAT,
  message_id: "m2",
  offset,
  text,
});

beforeEach(() => resetLive());

test("applyDelta appends in order, ignores repeats and reports gaps", () => {
  expect(applyDelta("", 0, "Hel")).toBe("Hel");
  expect(applyDelta("Hel", 3, "lo")).toBe("Hello");
  expect(applyDelta("Hello", 3, "lo")).toBe("Hello"); // seen already
  expect(applyDelta("Hello", 3, "lo!")).toBe("Hello!"); // partly seen
  expect(applyDelta("Hel", 5, "x")).toBeNull(); // a piece is missing
});

test("a reply streams into the store, then lands in the cache", () => {
  const queryClient = seeded([message("m1", "user", "hi")]);
  handleEvent(queryClient, {
    type: "message.created",
    chat_id: CHAT,
    message: message("m2", "bot", ""),
  });
  expect(useLiveStore.getState().streaming.m2).toBe("");

  handleEvent(queryClient, delta(0, "Hel"));
  handleEvent(queryClient, delta(3, "lo"));
  expect(useLiveStore.getState().streaming.m2).toBe("Hello");
  expect(contents(queryClient)).toEqual(["hi", ""]); // the cache waits for the end

  handleEvent(queryClient, {
    type: "message.completed",
    chat_id: CHAT,
    message_id: "m2",
    length: 5,
  });
  expect(contents(queryClient)).toEqual(["hi", "Hello"]);
  expect(useLiveStore.getState().streaming.m2).toBeUndefined();
});

test("the same message arriving twice is kept once", () => {
  const queryClient = seeded([]);
  const created = { type: "message.created", chat_id: CHAT, message: message("m1", "user", "hi") };
  handleEvent(queryClient, created);
  handleEvent(queryClient, created);
  expect(contents(queryClient)).toEqual(["hi"]);
});

test("a missed delta refetches the chat instead of showing broken text", () => {
  const queryClient = seeded([message("m2", "bot", "Hel")]);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  handleEvent(queryClient, delta(10, "late"));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: messagesKey(CHAT) });
  expect(useLiveStore.getState().streaming.m2).toBeUndefined();
});

test("deltas continue from the saved partial text after a refetch", () => {
  const queryClient = seeded([message("m2", "bot", "Hel")]);
  handleEvent(queryClient, delta(3, "lo"));
  expect(useLiveStore.getState().streaming.m2).toBe("Hello");
});

test("a completed length mismatch refetches", () => {
  const queryClient = seeded([message("m2", "bot", "")]);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  handleEvent(queryClient, delta(0, "Hel"));
  handleEvent(queryClient, {
    type: "message.completed",
    chat_id: CHAT,
    message_id: "m2",
    length: 99,
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: messagesKey(CHAT) });
});

test("run status drives the working dot", () => {
  const queryClient = seeded([]);
  const status = (value: string) =>
    handleEvent(queryClient, {
      type: "run.status",
      chat_id: CHAT,
      bot_id: BOT,
      run_id: "run-1",
      status: value,
    });
  status("queued");
  expect(useLiveStore.getState().working[BOT]).toBe(true);
  status("running");
  expect(useLiveStore.getState().working[BOT]).toBe(true);
  status("completed");
  expect(useLiveStore.getState().working[BOT]).toBe(false);
});

test("a failed run with no text removes the placeholder and shows the error", () => {
  const queryClient = seeded([message("m1", "user", "hi"), message("m2", "bot", "")]);
  handleEvent(queryClient, {
    type: "run.status",
    chat_id: CHAT,
    bot_id: BOT,
    status: "failed",
    message_id: "m2",
    message_kept: false,
    error: { code: "llm_rate_limited", message: "Claude is busy right now." },
  });
  expect(contents(queryClient)).toEqual(["hi"]);
  expect(useLiveStore.getState().errors[CHAT]).toBe("Claude is busy right now.");
  expect(useLiveStore.getState().working[BOT]).toBe(false);
});

test("a failed run keeps the partial text it produced", () => {
  const queryClient = seeded([message("m2", "bot", "")]);
  handleEvent(queryClient, delta(0, "Half"));
  handleEvent(queryClient, {
    type: "run.status",
    chat_id: CHAT,
    bot_id: BOT,
    status: "failed",
    message_id: "m2",
    message_kept: true,
    error: { code: "llm_failed", message: "Claude returned an error." },
  });
  expect(contents(queryClient)).toEqual(["Half"]);
});

test("a new run clears the old error", () => {
  const queryClient = seeded([]);
  useLiveStore.setState({ errors: { [CHAT]: "old" } });
  handleEvent(queryClient, { type: "run.status", chat_id: CHAT, bot_id: BOT, status: "queued" });
  expect(useLiveStore.getState().errors[CHAT]).toBeUndefined();
});

test("reconnecting drops live text and refetches Bots and messages", () => {
  const queryClient = seeded([]);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  useLiveStore.setState({ streaming: { m2: "Hel" }, working: { [BOT]: true } });
  handleReconnected(queryClient);
  expect(useLiveStore.getState().streaming).toEqual({});
  expect(useLiveStore.getState().working).toEqual({});
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["bots"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["messages"] });
});

const toolCall = (status: string, result: string | null) => ({
  id: "t1",
  run_id: "run-1",
  step: 0,
  tool: "web_fetch",
  risk: "safe",
  status,
  summary: "Opened example.com",
  result_summary: result,
  started_at: null,
  finished_at: null,
});

test("tool steps appear when they start and update when they finish", () => {
  const queryClient = seeded([message("m2", "bot", "")]);
  const steps = () => toolCallsByRun(queryClient.getQueryData(messagesKey(CHAT)))["run-1"];
  handleEvent(queryClient, {
    type: "tool.started",
    chat_id: CHAT,
    run_id: "run-1",
    tool_call: toolCall("pending", null),
  });
  expect(steps().map((step) => step.status)).toEqual(["pending"]);
  handleEvent(queryClient, {
    type: "tool.finished",
    chat_id: CHAT,
    run_id: "run-1",
    tool_call: toolCall("ok", "Read example.com"),
  });
  expect(steps()).toHaveLength(1);
  expect(steps()[0]).toMatchObject({ status: "ok", result_summary: "Read example.com" });
});

test("the run in progress is tracked so it can be stopped", () => {
  const queryClient = seeded([]);
  const status = (value: string, runId: string) =>
    handleEvent(queryClient, {
      type: "run.status",
      chat_id: CHAT,
      bot_id: BOT,
      run_id: runId,
      status: value,
    });
  status("queued", "run-1");
  expect(useLiveStore.getState().runs[CHAT]).toBe("run-1");
  status("running", "run-1");
  expect(useLiveStore.getState().runs[CHAT]).toBe("run-1");
  status("completed", "run-0"); // an older run finishing must not clear the current one
  expect(useLiveStore.getState().runs[CHAT]).toBe("run-1");
  status("cancelled", "run-1");
  expect(useLiveStore.getState().runs[CHAT]).toBeUndefined();
});

test("a stopped run keeps its partial text and shows no error", () => {
  const queryClient = seeded([message("m2", "bot", "")]);
  handleEvent(queryClient, delta(0, "Half"));
  handleEvent(queryClient, {
    type: "run.status",
    chat_id: CHAT,
    bot_id: BOT,
    run_id: "run-1",
    status: "cancelled",
    message_id: "m2",
    message_kept: true,
  });
  expect(contents(queryClient)).toEqual(["Half"]);
  expect(useLiveStore.getState().errors[CHAT]).toBeUndefined();
  expect(useLiveStore.getState().working[BOT]).toBe(false);
});

test("a run stopped before it said anything leaves no empty bubble", () => {
  const queryClient = seeded([message("m1", "user", "hi"), message("m2", "bot", "")]);
  handleEvent(queryClient, {
    type: "run.status",
    chat_id: CHAT,
    bot_id: BOT,
    run_id: "run-1",
    status: "cancelled",
    message_id: "m2",
    message_kept: false,
  });
  expect(contents(queryClient)).toEqual(["hi"]);
});

test("a paused run still counts as working and can still be stopped", () => {
  const queryClient = seeded([]);
  handleEvent(queryClient, {
    type: "run.status",
    chat_id: CHAT,
    bot_id: BOT,
    run_id: "run-1",
    status: "paused",
    takeover: true,
    reason: "Please sign in",
  });
  expect(useLiveStore.getState().working[BOT]).toBe(true);
  expect(useLiveStore.getState().runs[CHAT]).toBe("run-1");
});

test("computer status events update the store and the cached computer", () => {
  const queryClient = seeded([]);
  queryClient.setQueryData(["computer"], {
    id: "c1",
    status: "stopped",
    provider: "docker",
    last_active_at: null,
  });
  handleEvent(queryClient, { type: "computer.status", computer_id: "c1", status: "starting" });
  expect(useLiveStore.getState().computer).toBe("starting");
  expect(queryClient.getQueryData<{ status: string }>(["computer"])?.status).toBe("starting");
});

const APPROVAL = {
  id: "a1",
  run_id: "run-1",
  chat_id: CHAT,
  bot_id: BOT,
  tool_call_id: "t1",
  tool: "email_send",
  title: "Send email to sam@example.com",
  preview: { kind: "email", fields: { to: "sam@example.com" }, context: {} },
  status: "pending",
  created_at: "2026-01-01T00:00:00Z",
  resolved_at: null,
} as Approval;

test("a new approval joins the list and asks for a notification; an answer removes it", () => {
  const queryClient = seeded([]);
  queryClient.setQueryData<Approval[]>(approvalsKey, []);
  queryClient.setQueryData(["bots"], [{ id: BOT, name: "Inbox Bot" }]);

  handleEvent(queryClient, { type: "approval.created", approval: APPROVAL });
  handleEvent(queryClient, { type: "approval.created", approval: APPROVAL }); // a repeat

  expect(queryClient.getQueryData<Approval[]>(approvalsKey)).toEqual([APPROVAL]);
  expect(vi.mocked(tauri.notify)).toHaveBeenCalledWith(
    "Inbox Bot needs your approval",
    "Send email to sam@example.com",
  );

  handleEvent(queryClient, { type: "approval.resolved", approval_id: "a1", status: "approved" });
  expect(queryClient.getQueryData<Approval[]>(approvalsKey)).toEqual([]);
});

test("a run waiting for approval is still in progress, so it can be stopped", () => {
  const queryClient = seeded([]);
  handleEvent(queryClient, {
    type: "run.status",
    chat_id: CHAT,
    bot_id: BOT,
    run_id: "run-1",
    status: "waiting_approval",
  });
  expect(useLiveStore.getState().runs[CHAT]).toBe("run-1");
  expect(useLiveStore.getState().working[BOT]).toBe(true);
});

test("a chat that leaves the screen forgets its live text, so it cannot go stale", () => {
  const queryClient = seeded([message("m1", "user", "hi"), message("m2", "bot", "")]);
  handleEvent(queryClient, delta(0, "Drafting"));
  expect(useLiveStore.getState().streaming.m2).toBe("Drafting");

  dropChatStreaming(queryClient, CHAT);

  expect(useLiveStore.getState().streaming).toEqual({});
});
