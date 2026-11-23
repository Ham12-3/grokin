/**
 * Typed wrappers around the Rust core. Components never call `invoke` directly.
 * Every command here must exist in src-tauri/build.rs and capabilities/default.json.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type Provider = "google" | "email";

/** Shape of errors thrown by the Rust commands. */
export interface TauriError {
  code: string;
  message: string;
}

export function isTauriError(error: unknown): error is TauriError {
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as TauriError).code === "string" &&
    typeof (error as TauriError).message === "string"
  );
}

export function errorMessage(
  error: unknown,
  fallback = "Something went wrong. Try again.",
): string {
  if (isTauriError(error)) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/** Google opens the system browser. Email asks the API to send a magic link. */
export function authStartLogin(provider: Provider, email?: string): Promise<void> {
  return invoke("auth_start_login", { provider, email: email ?? null });
}

/** Whether a session exists in the OS keychain. The refresh token never reaches JS. */
export function authGetTokens(): Promise<{ has_session: boolean }> {
  return invoke("auth_get_tokens");
}

/** A valid access token; Rust refreshes it when needed. Keep it in memory only. */
export function authGetAccessToken(force = false): Promise<string> {
  return invoke("auth_get_access_token", { force });
}

export function authLogout(): Promise<void> {
  return invoke("auth_logout");
}

export function apiBaseUrl(): Promise<string> {
  return invoke("api_base_url");
}

export function appVersion(): Promise<string> {
  return invoke("app_version");
}

export function onAuthChanged(callback: (signedIn: boolean) => void): Promise<UnlistenFn> {
  return listen<{ signed_in: boolean }>("auth:changed", (event) =>
    callback(event.payload.signed_in),
  );
}

export function onAuthError(callback: (error: TauriError) => void): Promise<UnlistenFn> {
  return listen<TauriError>("auth:error", (event) => callback(event.payload));
}
