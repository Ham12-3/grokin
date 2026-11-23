import { beforeEach, expect, test, vi } from "vitest";
import { ApiError, apiFetch, resetApiClient } from "./client";
import * as tauri from "@/lib/tauri";

vi.mock("@/lib/tauri", () => ({
  apiBaseUrl: vi.fn(),
  authGetAccessToken: vi.fn(),
}));

const mocked = vi.mocked(tauri);

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetApiClient();
  mocked.apiBaseUrl.mockResolvedValue("http://api.test");
  mocked.authGetAccessToken.mockImplementation(async (force) => (force ? "fresh" : "stale"));
});

test("retries once with a fresh token after a 401", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(json({ error: { code: "token_expired", message: "Expired" } }, 401))
    .mockResolvedValueOnce(json({ ok: true }));

  await expect(apiFetch<{ ok: boolean }>("/me")).resolves.toEqual({ ok: true });

  expect(mocked.authGetAccessToken.mock.calls).toEqual([[false], [true]]);
  const tokens = fetchMock.mock.calls.map(([, init]) =>
    new Headers(init?.headers).get("Authorization"),
  );
  expect(tokens).toEqual(["Bearer stale", "Bearer fresh"]);
});

test("gives up after the second 401 and surfaces the API error", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () =>
      json({ error: { code: "invalid_token", message: "Invalid access token." } }, 401),
    );

  const error = await apiFetch("/me").catch((caught: unknown) => caught);

  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 401, code: "invalid_token" });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("non-JSON failures become a generic error", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("oops", { status: 500 }));
  await expect(apiFetch("/me")).rejects.toMatchObject({ status: 500, code: "http_error" });
});

test("204 responses resolve to undefined", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
  await expect(apiFetch("/anything", { method: "POST" })).resolves.toBeUndefined();
});
