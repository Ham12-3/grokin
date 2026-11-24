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
  run_id: null,
  created_at: "2026-01-01T00:00:00Z",
});

interface Call {
  method: string;
  path: string;
  body: unknown;
  auth: string | null;
}

/** A tiny in-memory API behind `fetch`. */
function fakeApi(initial: { bots?: (typeof BOT)[]; messages?: ReturnType<typeof message>[] }) {
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
      return json({ items: messages, has_more: false, active_run_id: null });
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
