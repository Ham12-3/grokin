# Phase 10: Release

Build phase 10 only. Read `docs/12-testing-release.md` and `docs/09-security.md` (checklist).

## Build

1. `tauri-plugin-updater` wired: check on start and every 6 hours, "Update ready, restart" in tray and settings, never restart mid-stream.
2. Generate updater keys (tell me the command; I keep the private key). Public key in `tauri.conf.json`.
3. `.github/workflows/release.yml` with `tauri-apps/tauri-action` on Windows, macOS (universal) and Ubuntu, triggered by `v*` tags, uploading installers and `latest.json` to a GitHub Release.
4. macOS signing + notarization and Windows signing steps reading the GitHub secrets listed in `docs/12-testing-release.md` (skip cleanly when secrets are missing so CI still builds unsigned).
5. App icons (all sizes from one 1024x1024 PNG with `pnpm tauri icon`), product name, bundle identifier `com.crew.desktop` (I may change it).
6. Sentry (or similar) for the API, worker and the React app. No secrets or message contents in error reports.
7. `/me` returns `min_desktop_version`; old apps show "Please update".
8. Dockerfile for `services` (api + worker, one image) and a short `docs/DEPLOY.md` for Fly.io or AWS.
9. Go through the security checklist in `docs/09-security.md` and fix anything that fails.

## Done means

- Tag `v0.1.0`: CI produces installers for all three OSes.
- Install v0.1.0, tag `v0.1.1`: the installed app updates itself.
- Security checklist all ticked.
- All checks pass.

Update PROGRESS.md, give me the release steps as a checklist, suggest a commit, then stop.
