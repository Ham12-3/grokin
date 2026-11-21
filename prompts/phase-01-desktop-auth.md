# Phase 1: Desktop shell and sign-in

Build phase 1 only. Read `docs/04-desktop-tauri.md`, `docs/05-backend-api.md` (Auth section), `docs/08-data-model.md` (users, refresh_tokens) and `docs/09-security.md`.

## Backend

1. Migrations for `users`, `refresh_tokens`, `audit_log`.
2. Auth routes: email magic link (in dev, print the link to the API log instead of emailing), Google OAuth (client id/secret from env), `/auth/callback` redirecting to `crew://auth?code=...`, `/auth/exchange` with PKCE, `/auth/refresh` with rotation, `/auth/logout`, `/me`.
3. JWT access tokens (15 min) signed with `JWT_SECRET`. Refresh tokens: random 48 bytes, store only the sha256 hash.
4. One-time codes in Redis with a 60s TTL, single use.
5. Tests: happy path, expired code, reused code, refresh rotation (old token rejected), logout.

## Desktop (Rust)

1. Plugins: deep-link (scheme `crew`), single-instance (forward deep links to the running app), store, notification, opener, window-state, log, autostart.
2. `auth.rs`: `auth_start_login(provider)` creates a PKCE verifier (kept in memory), opens the system browser. Deep link handler exchanges the code, saves the refresh token in the OS keychain (`keyring` crate, service `crew`), emits `auth:changed`.
3. `auth_get_access_token()` refreshes when needed and returns only the access token. `auth_logout()`.
4. `tray.rs`: tray icon and menu (Open Crew, Quit). Closing the window hides it; Quit exits.
5. Add every command to capabilities.

## Desktop (React)

1. `src/lib/tauri.ts` typed wrappers.
2. Sign-in screen (email field + "Continue with Google"), a "Check your email" state, and a signed-in placeholder home that shows the user's name from `/me` and a Sign out button.
3. API client with automatic access-token refresh through `auth_get_access_token()`.
4. Generate API types from OpenAPI (`pnpm gen:api` using openapi-typescript).

## Done means

- Email sign-in works end to end in dev (click the printed link).
- Google sign-in works (if keys are set).
- On Windows, with the app already open, the deep link reaches the same window (no second app).
- Restart the app: still signed in (keychain). Sign out: keychain entry gone.
- Close button hides to tray; tray Quit exits.
- All checks pass.

Update PROGRESS.md, give me manual test steps, suggest a commit, then stop.
