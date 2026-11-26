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
  notify: vi.fn(),
  setTrayBadge: vi.fn(),
  onOpenApprovals: vi.fn(),
  onPauseAllRoutines: vi.fn(),
  saveFile: vi.fn(),
  appVersion: vi.fn(),
  updateStatus: vi.fn(),
  updateRestart: vi.fn(),
  onUpdateReady: vi.fn(),
  onUpdateRestartRequested: vi.fn(),
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
let emitOpenApprovals: () => void = () => {};
let emitPauseAll: () => void = () => {};
let emitUpdateReady: (version: string) => void = () => {};
let emitRestartRequested: () => void = () => {};
let minDesktopVersion = "0.1.0";

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
  card: null as Record<string, unknown> | null,
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

const APPROVAL = {
  id: "a1",
  run_id: "run-9",
  chat_id: "chat-1",
  bot_id: "bot-1",
  tool_call_id: "t9",
  tool: "email_send",
  title: "Send email to sam@example.com",
  preview: {
    kind: "email",
    fields: { to: "sam@example.com", subject: "Report", body: "The report is ready." },
    context: {},
  },
  status: "pending",
  created_at: "2026-01-01T00:00:00Z",
  resolved_at: null,
  from_routine: false,
};

const SKILL = {
  id: "s1",
  bot_id: "bot-1",
  slug: "weekly-report",
  name: "Weekly Report",
  description: "Summarise the week",
  steps: "1. Read notes.md",
  rules: "",
  created_at: "2026-01-01T00:00:00Z",
};

const ROUTINE = {
  id: "r1",
  bot_id: "bot-1",
  skill_id: "s1",
  skill_name: "Weekly Report",
  skill_slug: "weekly-report",
  trigger: { type: "cron", cron: "0 9 * * 1-5", timezone: "UTC" } as Record<string, string>,
  notify: true,
  paused: false,
  next_run_at: "2026-01-02T09:00:00Z" as string | null,
  last_run: null,
  webhook_url: null as string | null,
};

const GMAIL = {
  id: "c-gmail",
  kind: "gmail",
  name: "Gmail",
  status: "connected",
  url: null,
  tools: [],
};
const MCP = {
  id: "c-mcp",
  kind: "mcp",
  name: "Tickets",
  status: "connected",
  url: "https://mcp.example.com/mcp" as string | null,
  tools: [
    { name: "lookup", description: "Look up a ticket", safe: false },
    { name: "close", description: "Close a ticket", safe: false },
  ],
};

const LIBRARY_ITEM = {
  id: "lib-1",
  bot_id: "bot-1",
  run_id: null,
  kind: "file",
  category: "document",
  title: "Q3 report",
  path: "/workspace/outputs/q3.md",
  mime: "text/markdown",
  size_bytes: 2048,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function fakeApi(initial: {
  library?: (typeof LIBRARY_ITEM)[];
  groups?: { id: string; title: string; bot_ids: string[] }[];
  connectors?: (typeof MCP)[];
  botApps?: string[];
  vault?: string[];
  routines?: (typeof ROUTINE)[];
  memory?: string[];
  skills?: (typeof SKILL)[];
  approvals?: (typeof APPROVAL)[];
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
  const approvals = [...(initial.approvals ?? [])];
  const skills = [...(initial.skills ?? [])];
  const library = [...(initial.library ?? [])];
  const groups = (initial.groups ?? []).map((group) => ({
    ...group,
    kind: "group",
    last_message_at: null,
  }));
  const connectors = (initial.connectors ?? []).map((item) => ({ ...item }));
  let botApps = [...(initial.botApps ?? [])];
  const vault = (initial.vault ?? []).map((name, index) => ({
    id: `v-${index + 1}`,
    name,
    type: "api_key",
    created_at: "2026-01-01T00:00:00Z",
  }));
  const routines = (initial.routines ?? []).map((routine) => ({ ...routine }));
  const memory = (initial.memory ?? []).map((text, index) => ({
    id: `mem-${index + 1}`,
    bot_id: "bot-1",
    text,
    created_at: "2026-01-01T00:00:00Z",
  }));
  const messages = [...(initial.messages ?? [])];
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input).replace("http://api.test/api/v1", "");
    const method = init?.method ?? "GET";
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, auth: new Headers(init?.headers).get("Authorization") });

    if (path === "/me") {
      return json({
        email: "sam@example.com",
        name: "Sam",
        daily_token_budget: 1,
        min_desktop_version: minDesktopVersion,
      });
    }
    if (path === "/bots" && method === "GET") return json(bots);
    if (String(input).startsWith("http://api.test/files/")) {
      return new Response("# Q3 report\n\nRevenue is **up**.", { status: 200 });
    }
    if (path === "/chats" && method === "GET") return json(groups);
    if (path === "/chats" && method === "POST") {
      const ids = (body as { bot_ids: string[] }).bot_ids;
      const created = {
        id: "chat-g",
        kind: "group",
        title: "New group",
        bot_ids: ids,
        last_message_at: null,
      };
      groups.push(created);
      return json(created);
    }
    if (path.startsWith("/library/") && method === "GET") {
      const item = library.find((entry) => path.endsWith(entry.id));
      return json({ ...item, download_url: `http://api.test/files/${item?.id}` });
    }
    if (path.startsWith("/library/") && method === "DELETE") {
      library.splice(0, library.length);
      return new Response(null, { status: 204 });
    }
    if (path.startsWith("/library")) {
      const query = new URLSearchParams(path.split("?")[1] ?? "");
      const q = (query.get("q") ?? "").toLowerCase();
      const category = query.get("category");
      return json(
        library.filter(
          (item) =>
            item.title.toLowerCase().includes(q) && (!category || item.category === category),
        ),
      );
    }
    if (path === "/vault" && method === "GET") return json(vault);
    if (path === "/vault" && method === "POST") {
      const input = body as { name: string; type: string };
      const item = { id: "v-new", name: input.name, type: input.type, created_at: "" };
      vault.push(item);
      return json(item, 201);
    }
    if (path.startsWith("/vault/") && method === "DELETE") {
      vault.splice(0, vault.length);
      return new Response(null, { status: 204 });
    }
    if (path === "/connectors" && method === "GET") {
      return json({
        available: [
          { kind: "gmail", name: "Gmail" },
          { kind: "slack", name: "Slack" },
        ],
        connected: connectors,
        configured: true,
      });
    }
    if (path === "/connectors/mcp") {
      const input = body as { name: string; url: string };
      const server = { ...MCP, id: "c-new", name: input.name, url: input.url };
      connectors.push(server);
      return json(server, 201);
    }
    if (path.startsWith("/connectors/") && path.endsWith("/connect")) {
      const kind = path.split("/")[2];
      const started = { ...GMAIL, id: `c-${kind}`, kind, name: kind, status: "pending" };
      connectors.push(started as unknown as typeof MCP);
      return json({ connector: started, url: `https://connect.example/${kind}` });
    }
    if (path.startsWith("/connectors/") && method === "PATCH") {
      const safe = (body as { safe_tools: string[] }).safe_tools;
      const server = connectors.find((item) => path.endsWith(item.id));
      if (server)
        server.tools = server.tools.map((tool) => ({ ...tool, safe: safe.includes(tool.name) }));
      return json(server);
    }
    if (path.startsWith("/connectors/") && method === "DELETE") {
      const index = connectors.findIndex((item) => path.endsWith(item.id));
      connectors.splice(index, 1);
      return new Response(null, { status: 204 });
    }
    if (path.endsWith("/apps") && method === "GET") return json({ connector_ids: botApps });
    if (path.endsWith("/apps") && method === "PUT") {
      botApps = (body as { connector_ids: string[] }).connector_ids;
      return json({ connector_ids: botApps });
    }
    if (path.endsWith("/routines") && method === "GET") return json(routines);
    if (path === "/routines/preview") {
      const cron = (body as { cron: string }).cron;
      if (cron.split(" ").length !== 5) {
        return json(
          { error: { code: "invalid_schedule", message: "That schedule is not valid." } },
          422,
        );
      }
      return json({ next_runs: ["2026-01-02T09:00:00Z", "2026-01-03T09:00:00Z"] });
    }
    if (path === "/routines/pause-all") {
      routines.forEach((routine) => Object.assign(routine, { paused: true, next_run_at: null }));
      return json({ paused: routines.length });
    }
    if (path.endsWith("/routines") && method === "POST") {
      const input = body as { trigger: Record<string, string> };
      const webhook = input.trigger.type === "webhook";
      const created = {
        ...ROUTINE,
        id: "r-new",
        trigger: input.trigger,
        webhook_url: webhook ? "http://api.test/api/v1/webhooks/routines/r-new/s3cret" : null,
      };
      routines.push({ ...created, webhook_url: null });
      return json(created, 201);
    }
    if (path.startsWith("/routines/") && path.endsWith("/runs")) {
      return json([
        {
          run_id: "run-9",
          status: "completed",
          source: "schedule",
          created_at: "2026-01-01T09:00:00Z",
          finished_at: "2026-01-01T09:00:05Z",
          error: null,
          reply: "Here is the weekly report.",
          tool_calls: [TOOL_CALL],
        },
      ]);
    }
    if (path.startsWith("/routines/") && method === "POST") {
      const [, , id, action] = path.split("/");
      const routine = routines.find((item) => item.id === id);
      if (routine && action !== "test") routine.paused = action === "pause";
      return json(routine ?? {}, action === "test" ? 202 : 200);
    }
    if (path.startsWith("/routines/") && method === "DELETE") {
      routines.splice(0, routines.length);
      return new Response(null, { status: 204 });
    }
    if (path.endsWith("/memory") && method === "GET") return json(memory);
    if (path.endsWith("/memory") && method === "POST") {
      const line = { ...memory[0], id: "mem-new", text: (body as { text: string }).text };
      memory.push(line);
      return json(line, 201);
    }
    if (path.includes("/memory/")) {
      const index = memory.findIndex((line) => path.endsWith(line.id));
      if (method === "DELETE") {
        memory.splice(index, 1);
        return new Response(null, { status: 204 });
      }
      memory[index] = { ...memory[index], text: (body as { text: string }).text };
      return json(memory[index]);
    }
    if (path.endsWith("/skills") && method === "GET") return json(skills);
    if (path.endsWith("/skills") && method === "POST") {
      const created = { ...SKILL, ...(body as object), id: "s-new", slug: "new-skill" };
      skills.push(created);
      return json(created, 201);
    }
    if (path.startsWith("/skills/") && method === "DELETE") {
      skills.splice(0, skills.length);
      return new Response(null, { status: 204 });
    }
    if (path.includes("/skill-drafts/") && method === "POST") {
      const [, , , , id, action] = path.split("/");
      const index = messages.findIndex((item) => item.id === id);
      const status = action === "save" ? "saved" : "cancelled";
      messages[index] = {
        ...messages[index],
        card: { ...messages[index].card, status, slug: "weekly-report" },
      };
      if (action === "save") skills.push(SKILL);
      return json(messages[index]);
    }
    if (path.startsWith("/approvals") && method === "GET") return json(approvals);
    if (path.startsWith("/approvals/") && method === "POST") {
      const [, , id, action] = path.split("/");
      const index = approvals.findIndex((item) => item.id === id);
      if (index < 0) {
        return json({ error: { code: "approval_resolved", message: "Already answered." } }, 409);
      }
      const [answered] = approvals.splice(index, 1);
      return json({ ...answered, status: action === "approve" ? "approved" : "rejected" });
    }
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
  mocked.notify.mockResolvedValue(true);
  mocked.setTrayBadge.mockResolvedValue();
  mocked.onOpenApprovals.mockImplementation(async (callback) => {
    emitOpenApprovals = callback;
    return () => {};
  });
  mocked.onPauseAllRoutines.mockImplementation(async (callback) => {
    emitPauseAll = callback;
    return () => {};
  });
  minDesktopVersion = "0.1.0";
  mocked.appVersion.mockResolvedValue("0.1.0");
  mocked.updateStatus.mockResolvedValue(null);
  mocked.updateRestart.mockResolvedValue(true);
  mocked.onUpdateReady.mockImplementation(async (callback) => {
    emitUpdateReady = callback;
    return () => {};
  });
  mocked.onUpdateRestartRequested.mockImplementation(async (callback) => {
    emitRestartRequested = callback;
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
  expect(post?.body).toEqual({ content: "What is on today?", skill_id: null });
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

test("Settings shows the computer and can restart it", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], computer: "running" });
  render(<App />);
  await screen.findByRole("log");
  fireEvent.click(screen.getByRole("button", { name: "Toggle details" }));
  const details = await screen.findByRole("complementary", { name: "Details" });
  fireEvent.mouseDown(within(details).getByRole("tab", { name: "Settings" }));

  const section = await within(details).findByRole("region", { name: "Your computer" });
  expect(within(section).getByRole("status")).toHaveTextContent("Running");
  fireEvent.click(within(section).getByRole("button", { name: "Restart" }));

  await waitFor(() => {
    const paths = calls.map((call) => call.path).filter((path) => path.startsWith("/computer/"));
    expect(paths).toEqual(["/computer/stop", "/computer/start"]);
  });
  expect(within(section).getByRole("status")).toHaveTextContent("Running");
});

// --- Approvals --------------------------------------------------------------------------

async function openChatWithApproval(approvals = [APPROVAL]) {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [{ ...BOT, working: true }], approvals, activeRunId: "run-9" });
  render(<App />);
  await screen.findByRole("log");
  const card = await screen.findByRole("article", {
    name: "Approval: Send email to sam@example.com",
  });
  return { calls, card };
}

const posts = (calls: Call[]) =>
  calls.filter((call) => call.method === "POST").map((call) => [call.path, call.body]);

test("an approval card shows the email and Approve sends it as drafted", async () => {
  const { calls, card } = await openChatWithApproval();
  expect(within(card).getByText("Inbox Bot needs your approval")).toBeInTheDocument();
  expect(within(card).getByText("sam@example.com")).toBeInTheDocument();
  expect(within(card).getByText("Report")).toBeInTheDocument();
  expect(within(card).getByText("The report is ready.")).toBeInTheDocument();
  // The sidebar counts it, the Bot shows it is waiting, and the tray is told.
  expect(screen.getByLabelText("1 pending")).toBeInTheDocument();
  expect(screen.getAllByRole("img", { name: "Waiting for you" }).length).toBeGreaterThan(0);
  await waitFor(() => expect(mocked.setTrayBadge).toHaveBeenLastCalledWith(1));

  fireEvent.click(within(card).getByRole("button", { name: "Approve" }));

  await waitFor(() => expect(posts(calls)).toEqual([["/approvals/a1/approve", {}]]));
  await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
  expect(screen.queryByLabelText("1 pending")).not.toBeInTheDocument();
  await waitFor(() => expect(mocked.setTrayBadge).toHaveBeenLastCalledWith(0));
});

test("Edit changes the draft and approves the edited version", async () => {
  const { calls, card } = await openChatWithApproval();
  fireEvent.click(within(card).getByRole("button", { name: "Edit" }));

  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByLabelText("To")).toHaveValue("sam@example.com");
  fireEvent.change(within(dialog).getByLabelText("Subject"), {
    target: { value: "Q3 report is ready" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve with changes" }));

  await waitFor(() =>
    expect(posts(calls)).toEqual([
      [
        "/approvals/a1/approve",
        {
          edited_args: {
            to: "sam@example.com",
            subject: "Q3 report is ready",
            body: "The report is ready.",
          },
        },
      ],
    ]),
  );
  await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
});

test("Reject tells the server and removes the card", async () => {
  const { calls, card } = await openChatWithApproval();
  fireEvent.click(within(card).getByRole("button", { name: "Reject" }));
  await waitFor(() => expect(posts(calls)).toEqual([["/approvals/a1/reject", {}]]));
  await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
});

test("an approval without a form is edited as JSON, and bad JSON is not sent", async () => {
  const generic = {
    ...APPROVAL,
    tool: "terminal_run",
    title: "Run a command on your computer",
    preview: { kind: "generic", fields: { cmd: "rm -rf build" }, context: {} },
  };
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], approvals: [generic as unknown as typeof APPROVAL] });
  render(<App />);
  const card = await screen.findByRole("article");
  fireEvent.click(within(card).getByRole("button", { name: "Edit" }));
  const dialog = await screen.findByRole("dialog");
  const details = within(dialog).getByLabelText("Details");

  fireEvent.change(details, { target: { value: "{not json" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve with changes" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("not valid JSON");
  expect(posts(calls)).toEqual([]);

  fireEvent.change(details, { target: { value: '{"cmd": "rm -rf build/tmp"}' } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve with changes" }));
  await waitFor(() =>
    expect(posts(calls)).toEqual([
      ["/approvals/a1/approve", { edited_args: { cmd: "rm -rf build/tmp" } }],
    ]),
  );
});

test("the Approvals screen lists everything pending, grouped by Bot", async () => {
  const other = {
    ...BOT,
    id: "bot-2",
    name: "Social Bot",
    is_primary: false,
    direct_chat_id: "chat-2",
  };
  const post = {
    ...APPROVAL,
    id: "a2",
    bot_id: "bot-2",
    chat_id: "chat-2",
    tool: "social_post",
    title: "Publish a post",
    preview: { kind: "post", fields: { text: "We shipped!" }, context: {} },
  };
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT, other], approvals: [APPROVAL, post as unknown as typeof APPROVAL] });
  render(<App />);
  await screen.findByRole("log");
  expect(await screen.findByLabelText("2 pending")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Approvals/ }));
  const page = await screen.findByRole("region", { name: "Approvals" });
  const inbox = within(page).getByRole("region", { name: "Inbox Bot" });
  const social = within(page).getByRole("region", { name: "Social Bot" });
  expect(within(inbox).getByText("Send email to sam@example.com")).toBeInTheDocument();
  expect(within(social).getByText("We shipped!")).toBeInTheDocument();

  // "Open chat" goes back to that Bot.
  fireEvent.click(within(social).getByRole("button", { name: "Open chat" }));
  expect(await screen.findByRole("heading", { name: /Social Bot/ })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Approvals" })).not.toBeInTheDocument();
});

test("the tray menu or a notification opens the Approvals screen", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT] });
  render(<App />);
  await screen.findByRole("log");
  await waitFor(() => expect(mocked.onOpenApprovals).toHaveBeenCalled());

  act(() => emitOpenApprovals());

  const page = await screen.findByRole("region", { name: "Approvals" });
  expect(await within(page).findByText("Nothing is waiting for you.")).toBeInTheDocument();
});

// --- Memory and skills ------------------------------------------------------------------

async function openTab(name: string) {
  fireEvent.click(screen.getByRole("button", { name: "Toggle details" }));
  const details = await screen.findByRole("complementary", { name: "Details" });
  fireEvent.click(within(details).getByRole("tab", { name }));
  return details;
}

test("the Memory tab lists lines and lets the user add, edit and delete them", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], memory: ["Prefers short bullet summaries"] });
  render(<App />);
  await screen.findByRole("log");
  const details = await openTab("Memory");
  const list = await within(details).findByRole("list", { name: "Memory" });
  expect(await within(list).findByText("Prefers short bullet summaries")).toBeInTheDocument();

  fireEvent.change(within(details).getByLabelText("New memory line"), {
    target: { value: "Lives in Lagos" },
  });
  fireEvent.click(within(details).getByRole("button", { name: "Add line" }));
  expect(await within(list).findByText("Lives in Lagos")).toBeInTheDocument();

  fireEvent.click(within(list).getByRole("button", { name: "Edit: Lives in Lagos" }));
  fireEvent.change(within(list).getByLabelText("Memory line"), {
    target: { value: "Lives in Abuja" },
  });
  fireEvent.click(within(list).getByRole("button", { name: "Save line" }));
  expect(await within(list).findByText("Lives in Abuja")).toBeInTheDocument();

  fireEvent.click(
    within(list).getByRole("button", { name: "Delete: Prefers short bullet summaries" }),
  );
  await waitFor(() =>
    expect(within(list).queryByText("Prefers short bullet summaries")).not.toBeInTheDocument(),
  );
  expect(
    calls
      .filter((call) => call.method !== "GET" && call.path.includes("/memory"))
      .map((call) => [call.method, call.path, call.body]),
  ).toEqual([
    ["POST", "/bots/bot-1/memory", { text: "Lives in Lagos" }],
    ["PATCH", "/bots/bot-1/memory/mem-new", { text: "Lives in Abuja" }],
    ["DELETE", "/bots/bot-1/memory/mem-1", undefined],
  ]);
});

test("the Skills tab creates a skill and runs one now", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], skills: [SKILL] });
  render(<App />);
  await screen.findByRole("log");
  const details = await openTab("Skills");
  expect(await within(details).findByText("/weekly-report")).toBeInTheDocument();

  fireEvent.click(within(details).getByRole("button", { name: "New skill" }));
  const dialog = await screen.findByRole("dialog");
  const save = within(dialog).getByRole("button", { name: "Save skill" });
  expect(save).toBeDisabled(); // a skill needs a name and steps
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "New Skill" } });
  fireEvent.change(within(dialog).getByLabelText("Steps (markdown)"), {
    target: { value: "1. Do it" },
  });
  fireEvent.click(save);
  expect(await within(details).findByText("/new-skill")).toBeInTheDocument();

  fireEvent.click(within(details).getByRole("button", { name: "Run Weekly Report now" }));
  await waitFor(() =>
    expect(
      calls.find((call) => call.path === "/chats/chat-1/messages" && call.method === "POST")?.body,
    ).toEqual({
      content: "/weekly-report",
      skill_id: "s1",
    }),
  );
});

test("typing / in the composer picks a skill and sends it with the message", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const other = { ...SKILL, id: "s2", slug: "inbox-zero", name: "Inbox Zero", description: "" };
  const calls = fakeApi({ bots: [BOT], skills: [SKILL, other] });
  render(<App />);
  await screen.findByRole("log");
  const box = screen.getByLabelText("Message Inbox Bot");

  fireEvent.change(box, { target: { value: "/" } });
  const picker = await screen.findByRole("listbox", { name: "Skills" });
  await waitFor(() => expect(within(picker).getAllByRole("option")).toHaveLength(2));
  fireEvent.change(box, { target: { value: "/week" } }); // search
  expect(within(picker).getAllByRole("option")).toHaveLength(1);
  fireEvent.keyDown(box, { key: "Enter" }); // picks, does not send
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(calls.some((call) => call.method === "POST")).toBe(false);

  fireEvent.change(box, { target: { value: "for last week" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() =>
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      content: "/weekly-report for last week",
      skill_id: "s1",
    }),
  );
});

test("a skill draft card saves the skill only when the user clicks Save", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const draft = {
    ...message("m-draft", "system", ""),
    bot_id: "bot-1",
    card: {
      type: "skill_draft",
      status: "draft",
      name: "Weekly Report",
      description: "Summarise the week",
      steps: "1. Read notes.md",
      rules: "",
    },
  };
  const calls = fakeApi({ bots: [BOT], messages: [message("m1", "user", "save that"), draft] });
  render(<App />);
  const card = await screen.findByRole("article", { name: "Skill draft: Weekly Report" });
  expect(within(card).getByText("1. Read notes.md")).toBeInTheDocument();
  expect(calls.some((call) => call.method === "POST")).toBe(false);

  fireEvent.click(within(card).getByRole("button", { name: "Save skill" }));

  expect(await within(card).findByRole("status")).toHaveTextContent("/weekly-report");
  expect(within(card).queryByRole("button", { name: "Save skill" })).not.toBeInTheDocument();
  expect(calls.find((call) => call.method === "POST")?.path).toBe(
    "/chats/chat-1/skill-drafts/m-draft/save",
  );
});

test("a handoff note opens the other Bot's chat, which shows who passed the task on", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const research = {
    ...BOT,
    id: "bot-2",
    name: "Research Bot",
    is_primary: false,
    direct_chat_id: "chat-2",
  };
  const note = {
    ...message("m-note", "system", "Passed to Research Bot"),
    card: { type: "handoff", bot_id: "bot-2", bot_name: "Research Bot", chat_id: "chat-2" },
  };
  const task = {
    ...message("m-task", "user", "Research Tauri"),
    card: { type: "handoff_from", bot_id: "bot-1", bot_name: "Inbox Bot", chat_id: "chat-1" },
  };
  fakeApi({ bots: [BOT, research], messages: [note, task] });
  render(<App />);
  await screen.findByRole("log");

  fireEvent.click(await screen.findByRole("button", { name: /Passed to Research Bot/ }));

  expect(await screen.findByRole("heading", { name: /Research Bot/ })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Passed on by Inbox Bot" })).toBeInTheDocument();
});

// --- Routines ---------------------------------------------------------------------------

test("the Routines tab lists routines and can pause, run and show history", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], skills: [SKILL], routines: [ROUTINE] });
  render(<App />);
  await screen.findByRole("log");
  const details = await openTab("Routines");
  const list = await within(details).findByRole("list", { name: "Routines" });
  expect(await within(list).findByText("Weekly Report")).toBeInTheDocument();
  expect(within(list).getByText(/Every weekday at 09:00.* · Next:/)).toBeInTheDocument();
  expect(within(list).getByText("Has not run yet")).toBeInTheDocument();

  fireEvent.click(within(list).getByRole("button", { name: "Pause Weekly Report" }));
  expect(
    await within(list).findByRole("button", { name: "Resume Weekly Report" }),
  ).toBeInTheDocument();
  fireEvent.click(within(list).getByRole("button", { name: "Run Weekly Report now" }));
  await waitFor(() =>
    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual([
      "/routines/r1/pause",
      "/routines/r1/test",
    ]),
  );

  fireEvent.click(within(list).getByRole("button", { name: "History of Weekly Report" }));
  const history = await within(list).findByRole("list", { name: "History of Weekly Report" });
  expect(within(history).getByText("Here is the weekly report.")).toBeInTheDocument();
  expect(within(history).getByText("Opened example.com")).toBeInTheDocument();
});

test("a new routine previews its schedule, and a webhook routine shows its address once", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], skills: [SKILL] });
  render(<App />);
  await screen.findByRole("log");
  const details = await openTab("Routines");
  fireEvent.click(within(details).getByRole("button", { name: "New routine" }));
  let dialog = await screen.findByRole("dialog");

  // Every weekday at 07:30: the preview says so in words and the routine is created.
  fireEvent.change(within(dialog).getByLabelText("When"), { target: { value: "weekdays" } });
  fireEvent.change(within(dialog).getByLabelText(/^Time/), { target: { value: "07:30" } });
  expect(await within(dialog).findByText(/Every weekday at 07:30.*Next:/)).toBeInTheDocument();

  // A custom schedule that is not valid cannot be saved.
  fireEvent.change(within(dialog).getByLabelText("When"), { target: { value: "custom" } });
  fireEvent.change(within(dialog).getByLabelText(/^Schedule/), { target: { value: "soon" } });
  expect(await within(dialog).findByText("That schedule is not valid.")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Create routine" })).toBeDisabled();

  fireEvent.change(within(dialog).getByLabelText("When"), { target: { value: "weekdays" } });
  const create = within(dialog).getByRole("button", { name: "Create routine" });
  await waitFor(() => expect(create).toBeEnabled());
  fireEvent.click(create);
  await waitFor(() =>
    expect(
      calls.find((call) => call.path === "/bots/bot-1/routines" && call.method === "POST")?.body,
    ).toEqual({
      skill_id: "s1",
      trigger: { type: "cron", cron: "30 7 * * 1-5", timezone: expect.any(String) as string },
      notify: true,
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  // A webhook routine: the secret address appears once.
  fireEvent.click(within(details).getByRole("button", { name: "New routine" }));
  dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("When"), { target: { value: "webhook" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Create routine" }));
  expect(
    await within(details).findByText("http://api.test/api/v1/webhooks/routines/r-new/s3cret"),
  ).toBeInTheDocument();
  fireEvent.click(within(details).getByRole("button", { name: "Done" }));
  expect(within(details).queryByText(/s3cret/)).not.toBeInTheDocument();
});

test("the tray's Pause all routines pauses them", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT], skills: [SKILL], routines: [{ ...ROUTINE }] });
  render(<App />);
  await screen.findByRole("log");
  const details = await openTab("Routines");
  await within(details).findByRole("button", { name: "Pause Weekly Report" });
  await waitFor(() => expect(mocked.onPauseAllRoutines).toHaveBeenCalled());

  act(() => emitPauseAll());

  expect(
    await within(details).findByRole("button", { name: "Resume Weekly Report" }),
  ).toBeInTheDocument();
  expect(calls.some((call) => call.path === "/routines/pause-all")).toBe(true);
});

// --- Settings: Vault, connectors, apps --------------------------------------------------

async function openSettings() {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  render(<App />);
  await screen.findByRole("log");
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  return screen.findByRole("region", { name: "Settings" });
}

test("the Vault takes a secret once and never shows it again", async () => {
  const calls = fakeApi({ bots: [BOT], vault: ["old_key"] });
  const settings = await openSettings();
  const vault = within(settings).getByRole("region", { name: "Vault" });
  expect(await within(vault).findByText("old_key")).toBeInTheDocument();

  const value = within(vault).getByLabelText("Value");
  expect(value).toHaveAttribute("type", "password"); // masked while typing
  fireEvent.change(within(vault).getByLabelText("Name"), { target: { value: "GitHub_Token" } });
  fireEvent.change(value, { target: { value: "ghp_secret123" } });
  fireEvent.click(within(vault).getByRole("button", { name: "Add to Vault" }));

  expect(await within(vault).findByText("github_token")).toBeInTheDocument();
  expect(calls.find((call) => call.path === "/vault" && call.method === "POST")?.body).toEqual({
    name: "github_token",
    type: "api_key",
    value: "ghp_secret123",
  });
  // Saved: the field is empty and the value is nowhere on the page.
  expect(value).toHaveValue("");
  expect(document.body.textContent).not.toContain("ghp_secret123");

  fireEvent.click(within(vault).getByRole("button", { name: "Delete old_key" }));
  await waitFor(() => expect(within(vault).queryByText("old_key")).not.toBeInTheDocument());
});

test("connecting an app opens the sign-in page in the browser", async () => {
  const calls = fakeApi({ bots: [BOT] });
  const settings = await openSettings();
  const section = within(settings).getByRole("region", { name: "Connectors" });

  fireEvent.click(await within(section).findByRole("button", { name: "Connect Gmail" }));

  await waitFor(() =>
    expect(mocked.openExternal).toHaveBeenCalledWith("https://connect.example/gmail"),
  );
  expect(await within(section).findByText("Finish in your browser")).toBeInTheDocument();
  expect(calls.some((call) => call.path === "/connectors/gmail/connect")).toBe(true);
  fireEvent.click(within(section).getByRole("button", { name: "Disconnect Gmail" }));
  expect(await within(section).findByRole("button", { name: "Connect Gmail" })).toBeInTheDocument();
});

test("a custom MCP server lists its tools and each can be marked safe", async () => {
  const calls = fakeApi({ bots: [BOT] });
  const settings = await openSettings();
  const section = within(settings).getByRole("region", { name: "Connectors" });
  fireEvent.change(within(section).getByLabelText("Name"), { target: { value: "Tickets" } });
  fireEvent.change(within(section).getByLabelText("Address"), {
    target: { value: "https://mcp.example.com/mcp" },
  });
  fireEvent.click(within(section).getByRole("button", { name: "Add MCP server" }));

  const tools = await within(section).findByRole("list", { name: "Tools of Tickets" });
  expect(within(tools).getAllByText("asks every time")).toHaveLength(2);
  expect(calls.find((call) => call.path === "/connectors/mcp")?.body).toEqual({
    name: "Tickets",
    url: "https://mcp.example.com/mcp",
    headers_secret_ref: null,
  });

  fireEvent.click(within(tools).getByLabelText("lookup runs without asking"));
  await waitFor(() =>
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ safe_tools: ["lookup"] }),
  );
  expect(await within(tools).findByText("runs without asking")).toBeInTheDocument();
});

test("the Apps tab ticks which connected apps a Bot may use", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({
    bots: [BOT],
    connectors: [GMAIL as unknown as typeof MCP, MCP],
    botApps: ["c-gmail"],
  });
  render(<App />);
  await screen.findByRole("log");
  const details = await openTab("Apps");
  const gmail = await within(details).findByLabelText("Gmail");
  const tickets = within(details).getByLabelText(/Tickets/);
  expect(gmail).toBeChecked();
  expect(tickets).not.toBeChecked();

  fireEvent.click(tickets);
  await waitFor(() => expect(tickets).toBeChecked());
  fireEvent.click(gmail);
  await waitFor(() => expect(gmail).not.toBeChecked());
  expect(calls.filter((call) => call.method === "PUT").map((call) => call.body)).toEqual([
    { connector_ids: ["c-gmail", "c-mcp"] },
    { connector_ids: ["c-mcp"] },
  ]);

  fireEvent.click(within(details).getByRole("button", { name: /Connect more apps/ }));
  expect(await screen.findByRole("region", { name: "Settings" })).toBeInTheDocument();
});

// --- Group chats ------------------------------------------------------------------------

const RESEARCH = {
  ...BOT,
  id: "bot-2",
  name: "Research Bot",
  avatar: "🔎",
  is_primary: false,
  direct_chat_id: "chat-2",
};

test("a new group chat is created from the + menu and opens", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const calls = fakeApi({ bots: [BOT, RESEARCH] });
  render(<App />);
  await screen.findByRole("log");
  fireEvent.click(screen.getByRole("button", { name: "New" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "New group chat" }));
  const dialog = await screen.findByRole("dialog");
  const create = within(dialog).getByRole("button", { name: "Create group" });
  fireEvent.click(within(dialog).getByLabelText(/Inbox Bot/));
  expect(create).toBeDisabled(); // a group needs at least two Bots
  fireEvent.click(within(dialog).getByLabelText(/Research Bot/));
  fireEvent.click(create);

  expect(await screen.findByRole("heading", { name: "New group" })).toBeInTheDocument();
  expect(calls.find((call) => call.path === "/chats" && call.method === "POST")?.body).toEqual({
    bot_ids: ["bot-1", "bot-2"],
  });
  expect(
    within(screen.getByRole("list", { name: "Groups" })).getByText("New group"),
  ).toBeInTheDocument();
});

test("a group shows who said what, and @ picks a Bot to mention", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const said = {
    ...message("m-r", "bot", "Tauri is a toolkit."),
    chat_id: "chat-g",
    bot_id: "bot-2",
  };
  const calls = fakeApi({
    bots: [BOT, RESEARCH],
    groups: [{ id: "chat-g", title: "Inbox Bot, Research Bot", bot_ids: ["bot-1", "bot-2"] }],
    messages: [said],
  });
  render(<App />);
  await screen.findByRole("log");
  fireEvent.click(await screen.findByRole("button", { name: /Inbox Bot, Research Bot/ }));

  const log = await screen.findByRole("log", { name: "Inbox Bot, Research Bot" });
  expect(await within(log).findByText("Research Bot")).toBeInTheDocument(); // the speaker
  expect(screen.queryByRole("button", { name: "Toggle details" })).not.toBeInTheDocument();

  const box = screen.getByLabelText("Message Inbox Bot, Research Bot");
  fireEvent.change(box, { target: { value: "hey @res" } });
  const picker = await screen.findByRole("listbox", { name: "Bots" });
  expect(within(picker).getAllByRole("option")).toHaveLength(1);
  fireEvent.keyDown(box, { key: "Enter" }); // picks the Bot, does not send
  expect(box).toHaveValue("hey @Research Bot ");
  fireEvent.change(box, { target: { value: "hey @Research Bot what is Tauri?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() =>
    expect(
      calls.find((call) => call.method === "POST" && call.path.includes("/messages")),
    ).toMatchObject({
      path: "/chats/chat-g/messages",
      body: { content: "hey @Research Bot what is Tauri?", skill_id: null },
    }),
  );
});

// --- Library ----------------------------------------------------------------------------

test("the Library lists files, filters, previews markdown and saves to the computer", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  mocked.saveFile.mockResolvedValue(true);
  const image = {
    ...LIBRARY_ITEM,
    id: "lib-2",
    title: "Logo",
    category: "image",
    mime: "image/png",
  };
  fakeApi({ bots: [BOT], library: [LIBRARY_ITEM, image] });
  render(<App />);
  await screen.findByRole("log");
  fireEvent.click(screen.getByRole("button", { name: "Library" }));
  const library = await screen.findByRole("region", { name: "Library" });
  const list = within(library).getByRole("list", { name: "Library items" });
  expect(await within(list).findByText("Q3 report")).toBeInTheDocument();
  expect(within(list).getAllByText("Inbox Bot · 2.0 KB")).toHaveLength(2);

  fireEvent.change(within(library).getByLabelText("Filter by type"), {
    target: { value: "image" },
  });
  await waitFor(() => expect(within(list).queryByText("Q3 report")).not.toBeInTheDocument());
  fireEvent.change(within(library).getByLabelText("Filter by type"), { target: { value: "" } });
  fireEvent.change(within(library).getByLabelText("Search the Library"), {
    target: { value: "q3" },
  });
  await waitFor(() => expect(within(list).queryByText("Logo")).not.toBeInTheDocument());

  fireEvent.click(within(list).getByRole("button", { name: /Q3 report/ }));
  const preview = await within(library).findByRole("complementary", { name: "Preview" });
  expect(
    await within(preview).findByRole("heading", { name: "Q3 report", level: 1 }),
  ).toBeInTheDocument();
  expect(within(preview).getByText("up").tagName).toBe("STRONG"); // rendered markdown

  fireEvent.click(within(preview).getByRole("button", { name: "Save to computer" }));
  expect(await within(preview).findByText("Saved to your computer.")).toBeInTheDocument();
  expect(mocked.saveFile).toHaveBeenCalledWith("http://api.test/files/lib-1", "q3.md");
});

test("a file card in the chat opens that item in the Library", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  const card = {
    ...message("m-file", "system", "Q3 report"),
    card: {
      type: "file",
      library_id: "lib-1",
      title: "Q3 report",
      mime: "text/markdown",
      size_bytes: 2048,
    },
  };
  fakeApi({ bots: [BOT], library: [LIBRARY_ITEM], messages: [card] });
  render(<App />);
  await screen.findByRole("log");

  fireEvent.click(await screen.findByRole("button", { name: "Open Q3 report in the Library" }));

  const library = await screen.findByRole("region", { name: "Library" });
  const preview = await within(library).findByRole("complementary", { name: "Preview" });
  expect(
    await within(preview).findByRole("heading", { name: "Q3 report", level: 1 }),
  ).toBeInTheDocument();
});

// --- Updates ----------------------------------------------------------------------------

test("a downloaded update can be installed from Settings", async () => {
  fakeApi({ bots: [BOT] });
  const settings = await openSettings();
  const updates = within(settings).getByRole("region", { name: "Updates" });
  expect(await within(updates).findByText("You are up to date.")).toBeInTheDocument();

  act(() => emitUpdateReady("0.1.1"));

  expect(await within(updates).findByRole("status")).toHaveTextContent("version 0.1.1");
  fireEvent.click(within(updates).getByRole("button", { name: "Restart to update" }));
  expect(mocked.updateRestart).toHaveBeenCalledTimes(1);
});

test("the app never restarts for an update while a Bot is replying", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  mocked.updateStatus.mockResolvedValue("0.1.1");
  fakeApi({ bots: [{ ...BOT, working: true }], activeRunId: "run-9" });
  render(<App />);
  await screen.findByRole("log");
  await waitFor(() => expect(useLiveStore.getState().runs["chat-1"]).toBe("run-9"));
  await waitFor(() => expect(mocked.onUpdateRestartRequested).toHaveBeenCalled());

  act(() => emitRestartRequested()); // the tray's "Update ready, restart"

  expect(mocked.updateRestart).not.toHaveBeenCalled();
  const updates = await screen.findByRole("region", { name: "Updates" });
  expect(within(updates).getByRole("button", { name: "Restart to update" })).toBeDisabled();
  expect(within(updates).getByText(/A Bot is working/)).toBeInTheDocument();

  // The reply ends: now the same request restarts.
  act(() => useLiveStore.setState({ runs: {} }));
  act(() => emitRestartRequested());
  expect(mocked.updateRestart).toHaveBeenCalledTimes(1);
});

test("an app older than the server allows is asked to update", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT] });
  minDesktopVersion = "0.2.0";
  render(<App />);
  await screen.findByRole("log");
  expect(await screen.findByText(/Please update Crew/)).toBeInTheDocument();
});

test("an up-to-date app sees no update notice", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  fakeApi({ bots: [BOT] });
  render(<App />);
  await screen.findByRole("log");
  await waitFor(() => expect(mocked.appVersion).toHaveBeenCalled());
  expect(screen.queryByText(/Please update Crew/)).not.toBeInTheDocument();
});
