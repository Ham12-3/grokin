import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import { useAuthStore } from "@/features/auth/auth-store";
import { resetLive, useLiveStore } from "@/features/realtime/live";
import { resetApiClient } from "@/lib/api/client";
import * as tauri from "@/lib/tauri";

vi.mock("@/lib/tauri", async (importOriginal) => ({
  ...(await importOriginal<typeof tauri>()),
  authStartLogin: vi.fn(),
  authGetTokens: vi.fn(),
  authGetAccessToken: vi.fn(),
  authLogout: vi.fn(),
  apiBaseUrl: vi.fn(),
  onAuthChanged: vi.fn(),
  onAuthError: vi.fn(),
  openExternal: vi.fn(),
}));

// No real WebSocket in unit tests; ws.test.ts and live.test.ts cover that layer.
vi.mock("@/features/realtime/connection", () => ({
  startRealtime: vi.fn(() => () => {}),
  subscribeChat: vi.fn(() => () => {}),
}));

// A stand-in for the noVNC client: records what the Screen tab asks of it.
const screens: { url: string; protocols: string[]; viewOnly: boolean; closed: boolean }[] = [];
vi.mock("@novnc/novnc", () => ({
  default: class FakeRfb extends EventTarget {
    private readonly record: (typeof screens)[number];
    scaleViewport = false;
    constructor(_target: HTMLElement, url: string, options: { wsProtocols: string[] }) {
      super();
      this.record = { url, protocols: options.wsProtocols, viewOnly: false, closed: false };
      screens.push(this.record);
      queueMicrotask(() => this.dispatchEvent(new Event("connect")));
    }
    set viewOnly(value: boolean) {
      this.record.viewOnly = value;
    }
    focus() {}
    disconnect() {
      this.record.closed = true;
    }
  },
}));

const mocked = vi.mocked(tauri);
let emitAuthChanged: (signedIn: boolean) => void = () => {};
let emitAuthError: (error: tauri.TauriError) => void = () => {};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const BOT = {
  id: "bot-1",
  name: "Inbox Bot",
  avatar: "📬",
  job: "Sorts my inbox",
  instructions: "",
  approval_mode: "ask_risky",
  is_primary: true,
  direct_chat_id: "chat-1",
  working: false,
  created_at: "2026-01-01T00:00:00Z",
};

const message = (id: string, role: string, content: string) => ({
  id,
  chat_id: "chat-1",
  role,
  bot_id: role === "bot" ? "bot-1" : null,
  content,
  run_id: null as string | null,
  created_at: "2026-01-01T00:00:00Z",
});

interface Call {
  method: string;
  path: string;
  body: unknown;
  auth: string | null;
}

/** A tiny in-memory API behind `fetch`. */
const TOOL_CALL = {
  id: "t1",
  run_id: "run-9",
  step: 0,
  tool: "web_fetch",
  risk: "safe",
  status: "ok",
  summary: "Opened example.com",
  result_summary: "Read example.com: Tauri releases",
  started_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:00:01.500Z",
};

function fakeApi(initial: {
  bots?: (typeof BOT)[];
  messages?: ReturnType<typeof message>[];
  toolCalls?: (typeof TOOL_CALL)[];
  activeRunId?: string;
  computer?: string;
}) {
  let computerStatus = initial.computer ?? "stopped";
  const computer = () => ({
    id: "computer-1",
    status: computerStatus,
    provider: "docker",
    last_active_at: null,
  });
  const bots = [...(initial.bots ?? [])];
  const messages = [...(initial.messages ?? [])];
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input).replace("http://api.test/api/v1", "");
    const method = init?.method ?? "GET";
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, auth: new Headers(init?.headers).get("Authorization") });

    if (path === "/me") {
      return json({ email: "sam@example.com", name: "Sam", daily_token_budget: 1 });
    }
    if (path === "/bots" && method === "GET") return json(bots);
    if (path === "/bots" && method === "POST") {
      const created = { ...BOT, ...(body as object), id: "bot-2", direct_chat_id: "chat-2" };
      created.is_primary = bots.length === 0;
      bots.push(created);
      return json(created, 201);
    }
    if (path.startsWith("/bots/") && method === "DELETE") {
      bots.splice(0, bots.length);
      return new Response(null, { status: 204 });
    }
    if (path.includes("/messages") && method === "GET") {
      return json({
        items: messages,
        has_more: false,
        active_run_id: initial.activeRunId ?? null,
        tool_calls: initial.toolCalls ?? [],
      });
    }
    if (path === "/computer") return json(computer());
    if (path === "/computer/start") {
      computerStatus = "running";
      return json(computer());
    }
    if (path === "/computer/stop") {
      computerStatus = "stopped";
      return json(computer());
    }
    if ((path.endsWith("/pause") || path.endsWith("/resume")) && method === "POST") {
      return json({ run_id: "run-9", status: "running" }, 202);
    }
    if (path.endsWith("/cancel") && method === "POST") {
      return json({ run_id: "run-9", status: "running" }, 202);
    }
    if (path.startsWith("/runs/") && method === "GET") {
      return json({
        id: "run-9",
        chat_id: "chat-1",
        bot_id: "bot-1",
        status: "completed",
        steps: 2,
        input_tokens: 1234,
        output_tokens: 56,
        error: null,
        created_at: "2026-01-01T00:00:00Z",
        started_at: "2026-01-01T00:00:00Z",
        finished_at: "2026-01-01T00:00:03Z",
      });
    }
    if (path.includes("/messages") && method === "POST") {
      const sent = message("m-new", "user", (body as { content: string }).content);
      messages.push(sent);
      return json({ message: sent, run_id: "run-1" }, 202);
    }
    return json({ error: { code: "not_found", message: "Not found" } }, 404);
  });
  return calls;
}

beforeEach(() => {
  vi.clearAllMocks();
  screens.length = 0;
  resetApiClient();
  resetLive();
  useAuthStore.setState({ status: "loading" });
  mocked.authGetTokens.mockResolvedValue({ has_session: false });
  mocked.authGetAccessToken.mockResolvedValue("test-access-token");
  mocked.apiBaseUrl.mockResolvedValue("http://api.test");
  mocked.authStartLogin.mockResolvedValue();
  mocked.authLogout.mockResolvedValue();
  mocked.onAuthChanged.mockImplementation(async (callback) => {
    emitAuthChanged = callback;
    return () => {};
  });
  mocked.onAuthError.mockImplementation(async (callback) => {
    emitAuthError = callback;
    return () => {};
  });
});

// --- Sign-in ----------------------------------------------------------------------------

test("email sign-in asks for a link, then shows 'Check your email'", async () => {
  render(<App />);
  const input = await screen.findByLabelText("Email");
  fireEvent.change(input, { target: { value: " sam@example.com " } });
  fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));

  expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  expect(mocked.authStartLogin).toHaveBeenCalledWith("email", "sam@example.com");
});

test("Google sign-in opens the browser flow", async () => {
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
  expect(
    await screen.findByRole("heading", { name: "Finish in your browser" }),
  ).toBeInTheDocument();
  expect(mocked.authStartLogin).toHaveBeenCalledWith("google");
});

test("a failed start shows the error message", async () => {
  mocked.authStartLogin.mockRejectedValue({ code: "network", message: "Could not reach Crew." });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Email"), {
    target: { value: "sam@example.com" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach Crew.");
});

test("a deep link error returns to the form with the message", async () => {
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Email"), {
    target: { value: "sam@example.com" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));
  await screen.findByRole("heading", { name: "Check your email" });

  act(() => emitAuthError({ code: "invalid_code", message: "This sign-in code has expired." }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This sign-in code has expired.");
  expect(screen.getByLabelText("Email")).toBeInTheDocument();
});

// --- Signed in --------------------------------------------------------------------------

test("a new user is asked to create their first Bot, and can", async () => {
  const calls = fakeApi({});
  render(<App />);
  await screen.findByLabelText("Email");
  act(() => emitAuthChanged(true));

  expect(await screen.findByRole("heading", { name: "Create your first Bot" })).toBeInTheDocument();
  expect(await screen.findByText("Sam")).toBeInTheDocument();
  expect(calls[0].auth).toBe("Bearer test-access-token");

  fireEvent.click(screen.getByRole("button", { name: "New Bot" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Research Bot" } });
  fireEvent.change(within(dialog).getByLabelText("Job"), { target: { value: "Finds facts" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Avatar 🔎" }));
  fireEvent.click(within(dialog).getByLabelText(/Always ask/));
  fireEvent.click(within(dialog).getByRole("button", { name: "Create Bot" }));

  const nav = await screen.findByRole("navigation", { name: "Bots" });
  expect(await within(nav).findByText("Research Bot")).toBeInTheDocument();
  expect(calls.find((call) => call.method === "POST" && call.path === "/bots")?.body).toEqual({
    name: "Research Bot",
    avatar: "🔎",
    job: "Finds facts",
    instructions: "",
    approval_mode: "always_ask",
  });
  // The new Bot's chat opens.
  expect(await screen.findByLabelText("Message Research Bot")).toBeInTheDocument();
});

test("an existing session opens the Primary Bot's chat with its history", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({
    bots: [BOT],
    messages: [message("m1", "user", "hello"), message("m2", "bot", "Hi **Sam**")],
  });
  render(<App />);

  const log = await screen.findByRole("log", { name: "Chat with Inbox Bot" });
  expect(await within(log).findByText("hello")).toBeInTheDocument();
  expect(within(log).getByText("Sam").tagName).toBe("STRONG");
  expect(screen.getAllByLabelText("Primary Bot").length).toBeGreaterThan(0);
  expect(screen.getAllByLabelText("Idle").length).toBeGreaterThan(0);
});

test("sending a message posts it and shows it once", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT] });
  render(<App />);

  const box = await screen.findByLabelText("Message Inbox Bot");
  await screen.findByRole("log");
  fireEvent.change(box, { target: { value: "What is on today?" } });
  fireEvent.keyDown(box, { key: "Enter" });

  const log = screen.getByRole("log");
  expect(await within(log).findByText("What is on today?")).toBeInTheDocument();
  expect(within(log).getAllByText("What is on today?")).toHaveLength(1);
  const post = calls.find((call) => call.method === "POST");
  expect(post?.path).toBe("/chats/chat-1/messages");
  expect(post?.body).toEqual({ content: "What is on today?" });
});

test("streaming text, the working dot and run errors show in the chat", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT], messages: [message("m2", "bot", "")] });
  render(<App />);
  const log = await screen.findByRole("log");

  act(() =>
    useLiveStore.setState({ streaming: { m2: "Thinking about it" }, working: { "bot-1": true } }),
  );
  expect(within(log).getByText("Thinking about it")).toBeInTheDocument();
  expect(screen.getAllByLabelText("Working").length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

  act(() => useLiveStore.setState({ errors: { "chat-1": "Claude is busy right now." } }));
  expect(screen.getByRole("alert")).toHaveTextContent("Claude is busy right now.");
});

test("the Reconnecting banner follows the connection", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT] });
  render(<App />);
  await screen.findByRole("log");
  expect(screen.queryByText("Reconnecting...")).toBeNull();
  act(() => useLiveStore.setState({ status: "reconnecting" }));
  expect(screen.getByRole("status")).toHaveTextContent("Reconnecting...");
  act(() => useLiveStore.setState({ status: "open" }));
  expect(screen.queryByText("Reconnecting...")).toBeNull();
});

test("a Bot can be deleted from its settings, after a confirm", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT] });
  render(<App />);
  await screen.findByRole("log");

  fireEvent.click(screen.getByRole("button", { name: "Toggle details" }));
  const details = await screen.findByRole("complementary", { name: "Details" });
  expect(within(details).getByLabelText("Name")).toHaveValue("Inbox Bot");
  fireEvent.click(within(details).getByRole("button", { name: "Delete Bot" }));

  const confirm = await screen.findByRole("alertdialog");
  expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  fireEvent.click(within(confirm).getByRole("button", { name: "Delete" }));

  expect(await screen.findByRole("heading", { name: "Create your first Bot" })).toBeInTheDocument();
  expect(calls.find((call) => call.method === "DELETE")?.path).toBe("/bots/bot-1");
});

test("Sign out returns to the sign-in screen", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT] });
  mocked.authLogout.mockImplementation(async () => emitAuthChanged(false));
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await waitFor(() => expect(mocked.authLogout).toHaveBeenCalled());
  expect(await screen.findByLabelText("Email")).toBeInTheDocument();
});

// --- Tools, Stop and run details ---------------------------------------------------------

test("tool steps show collapsed in the reply and expand to the safe result", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({
    bots: [BOT],
    messages: [{ ...message("m2", "bot", "Here is the summary."), run_id: "run-9" }],
    toolCalls: [TOOL_CALL],
  });
  render(<App />);
  const log = await screen.findByRole("log");

  const steps = await within(log).findByRole("list", { name: "Steps" });
  const summary = within(steps).getByText("Opened example.com");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(within(steps).getByText("Read example.com: Tauri releases")).toBeInTheDocument();
  expect(within(steps).getByText(/Done in 1\.5s/)).toBeInTheDocument();
});

test("Stop cancels the run in progress", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [{ ...BOT, working: true }], activeRunId: "run-9" });
  render(<App />);
  await screen.findByRole("log");

  fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
  await waitFor(() =>
    expect(calls.some((call) => call.method === "POST" && call.path === "/runs/run-9/cancel")).toBe(
      true,
    ),
  );
});

test("run details show steps, tools, tokens and duration", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({
    bots: [BOT],
    messages: [{ ...message("m2", "bot", "Done."), run_id: "run-9" }],
    toolCalls: [TOOL_CALL],
  });
  render(<App />);
  const log = await screen.findByRole("log");

  fireEvent.click(await within(log).findByRole("button", { name: "Details" }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("Finished")).toBeInTheDocument();
  expect(within(dialog).getByText("1,234 in, 56 out")).toBeInTheDocument();
  expect(within(dialog).getByText("3.0s")).toBeInTheDocument();
  expect(within(dialog).getByText("Opened example.com")).toBeInTheDocument();
});

// --- Computer and live screen -------------------------------------------------------------

async function openScreenTab() {
  fireEvent.click(screen.getByRole("button", { name: "Toggle details" }));
  const details = await screen.findByRole("complementary", { name: "Details" });
  fireEvent.click(within(details).getByRole("tab", { name: "Screen" }));
  return details;
}

test("the Screen tab starts a stopped computer and then shows the live screen", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT] });
  render(<App />);
  await screen.findByRole("log");
  const details = await openScreenTab();

  expect(await within(details).findByText(/Off\. It starts by itself/)).toBeInTheDocument();
  expect(screens).toHaveLength(0); // no connection to a computer that is off
  fireEvent.click(within(details).getByRole("button", { name: "Start" }));

  expect(await within(details).findByLabelText("Live screen")).toBeInTheDocument();
  expect(calls.some((call) => call.path === "/computer/start")).toBe(true);
  await waitFor(() => expect(screens).toHaveLength(1));
  expect(screens[0].url).toBe("ws://api.test/api/v1/computer/computer-1/vnc?bot_id=bot-1");
  // The token travels as a subprotocol, never in the URL.
  expect(screens[0].protocols).toEqual(["binary", "bearer.test-access-token"]);
  expect(screens[0].url).not.toContain("test-access-token");
  expect(screens[0].viewOnly).toBe(true); // watching, not controlling
});

test("Take over pauses the run and gives the user control; Give back resumes it", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({
    bots: [{ ...BOT, working: true }],
    activeRunId: "run-9",
    computer: "running",
  });
  render(<App />);
  await screen.findByRole("log");
  const details = await openScreenTab();
  await within(details).findByLabelText("Live screen");
  await waitFor(() => expect(screens).toHaveLength(1));

  fireEvent.click(within(details).getByRole("button", { name: "Take over" }));
  await waitFor(() => expect(calls.some((call) => call.path === "/runs/run-9/pause")).toBe(true));
  await waitFor(() => expect(screens[0].viewOnly).toBe(false));
  expect(within(details).getByText(/You are in control/)).toBeInTheDocument();

  fireEvent.click(within(details).getByRole("button", { name: "Give back" }));
  await waitFor(() => expect(calls.some((call) => call.path === "/runs/run-9/resume")).toBe(true));
  await waitFor(() => expect(screens[0].viewOnly).toBe(true));
});

test("a takeover request shows a card that opens the screen with the user in control", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({
    bots: [{ ...BOT, working: true }],
    messages: [{ ...message("m2", "bot", "I need you."), run_id: "run-9" }],
    toolCalls: [
      {
        ...TOOL_CALL,
        tool: "request_takeover",
        status: "pending", // what the live event carries while the Bot waits
        summary: "Needs you: Please sign in to GitHub",
        result_summary: null as unknown as string,
      },
    ],
    activeRunId: "run-9",
    computer: "running",
  });
  render(<App />);
  await screen.findByRole("log");

  const card = await screen.findByRole("group", { name: "Takeover request" });
  expect(card).toHaveTextContent("Inbox Bot needs you. Please sign in to GitHub");
  fireEvent.click(within(card).getByRole("button", { name: "Open screen" }));

  const details = await screen.findByRole("complementary", { name: "Details" });
  await within(details).findByLabelText("Live screen");
  await waitFor(() => expect(screens[0]?.viewOnly).toBe(false));

  fireEvent.click(within(card).getByRole("button", { name: "Give back" }));
  await waitFor(() => expect(calls.some((call) => call.path === "/runs/run-9/resume")).toBe(true));
  await waitFor(() => expect(screens[0].viewOnly).toBe(true));
});

test("the chat says when the computer is starting", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [{ ...BOT, working: true }], activeRunId: "run-9" });
  render(<App />);
  await screen.findByRole("log");
  act(() => useLiveStore.setState({ computer: "starting" }));
  expect(screen.getByText("Starting your computer, about 20 seconds...")).toBeInTheDocument();
  act(() => useLiveStore.setState({ computer: "running" }));
  expect(screen.queryByText("Starting your computer, about 20 seconds...")).toBeNull();
});
