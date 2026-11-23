/**
 * API client. Adds the access token and retries once with a fresh token on 401.
 * Response types come from the generated OpenAPI schema (`pnpm gen:api`).
 */
import { apiBaseUrl, authGetAccessToken } from "@/lib/tauri";
import type { components } from "./schema";

export type Schemas = components["schemas"];

const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let basePromise: Promise<string> | undefined;

function baseUrl(): Promise<string> {
  basePromise ??= apiBaseUrl();
  return basePromise;
}

/** For tests. */
export function resetApiClient(): void {
  basePromise = undefined;
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json();
    const error = (body as { error?: { code?: unknown; message?: unknown } }).error;
    if (typeof error?.code === "string" && typeof error.message === "string") {
      return new ApiError(response.status, error.code, error.message);
    }
  } catch {
    // Not JSON: fall through to the generic error.
  }
  return new ApiError(response.status, "http_error", `Request failed (${response.status}).`);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const base = await baseUrl();

  const send = async (forceRefresh: boolean): Promise<Response> => {
    const token = await authGetAccessToken(forceRefresh);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(`${base}${API_PREFIX}${path}`, { ...init, headers });
  };

  let response = await send(false);
  if (response.status === 401) {
    response = await send(true);
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
