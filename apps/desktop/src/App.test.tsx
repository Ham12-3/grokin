import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import { useAuthStore } from "@/features/auth/auth-store";
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

beforeEach(() => {
  vi.clearAllMocks();
  resetApiClient();
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

test("email sign-in asks for a link, then shows 'Check your email'", async () => {
  render(<App />);
  const input = await screen.findByLabelText("Email");
  fireEvent.change(input, { target: { value: " sam@example.com " } });
  fireEvent.click(screen.getByRole("button", { name: "Continue with email" }));

  expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  expect(mocked.authStartLogin).toHaveBeenCalledWith("email", "sam@example.com");
  expect(screen.getByText("sam@example.com")).toBeInTheDocument();
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

test("the deep link signs the user in and shows their name from /me", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(json({ email: "sam@example.com", name: "Sam" }));
  render(<App />);
  await screen.findByLabelText("Email");

  act(() => emitAuthChanged(true));

  expect(await screen.findByText("Sam")).toBeInTheDocument();
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://api.test/api/v1/me");
  expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer test-access-token");
});

test("an existing session skips sign-in, and Sign out returns to it", async () => {
  mocked.authGetTokens.mockResolvedValue({ has_session: true });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ email: "sam@example.com", name: null }));
  mocked.authLogout.mockImplementation(async () => emitAuthChanged(false));
  render(<App />);

  expect(await screen.findByText("sam@example.com")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

  await waitFor(() => expect(mocked.authLogout).toHaveBeenCalled());
  expect(await screen.findByLabelText("Email")).toBeInTheDocument();
});
