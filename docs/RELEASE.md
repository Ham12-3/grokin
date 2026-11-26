# Release checklist

How to ship a version of Crew. Do the one-time setup once; the rest for every release.

## One-time setup

- [ ] **Updater keys.** On your own machine (never in CI, never in the repo):
      `cd apps/desktop && pnpm tauri signer generate -w ~/.tauri/crew-updater.key`
      Choose a password. Keep the `.key` file and the password safe: without them you can
      never ship an update that installed apps accept.
- [ ] Put the **public** key it prints into `apps/desktop/src-tauri/tauri.conf.json` at
      `plugins.updater.pubkey` (replace `REPLACE_WITH_YOUR_UPDATER_PUBLIC_KEY`) and commit.
- [ ] GitHub secrets (Settings > Secrets and variables > Actions):
  - [ ] `TAURI_SIGNING_PRIVATE_KEY` (the contents of the `.key` file) and
        `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
  - [ ] macOS: `APPLE_CERTIFICATE` (base64 .p12), `APPLE_CERTIFICATE_PASSWORD`,
        `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (app-specific),
        `APPLE_TEAM_ID`
  - [ ] Windows: `WINDOWS_CERTIFICATE` (base64 .pfx), `WINDOWS_CERTIFICATE_PASSWORD`
- [ ] GitHub variables (same page, Variables tab):
  - [ ] `CREW_API_URL`: the public https address of your API. It is compiled into the app
        and is the only address the app may talk to.
  - [ ] `VITE_SENTRY_DSN` (optional): error reports from the app
- [ ] If the repository is not `Ham12-3/grokin`, change `plugins.updater.endpoints` in
      `tauri.conf.json` to your repository.
- [ ] Deploy the backend (`docs/DEPLOY.md`).

Any missing secret is skipped with a warning: no signing certificate gives an unsigned
installer, no updater key gives installers that cannot update themselves.

## Every release

- [ ] `make check` passes, and `make check-slow` on a machine with Docker.
- [ ] `make check-secrets` passes (no secret value in the test suite's output).
- [ ] Security checklist below is all ticked.
- [ ] Same version number in all three places:
      `apps/desktop/src-tauri/tauri.conf.json`, `apps/desktop/src-tauri/Cargo.toml`,
      `services/shared/crew/__init__.py` (and `apps/desktop/package.json`).
- [ ] If this API version breaks older apps, raise `MIN_DESKTOP_VERSION` on the server
      **after** the new app is out.
- [ ] Deploy the backend first (migrations, then API, then worker).
- [ ] `git tag v0.1.0 && git push origin v0.1.0` (the tag must match the version).
- [ ] Wait for the Release workflow. It creates a **draft** GitHub Release with the
      installers and `latest.json`.
- [ ] Download and install each installer once. Sign in, send a message.
- [ ] Publish the draft. Installed apps find it within 6 hours (or at their next start).

## Checking that updates work (first time)

- [ ] Install v0.1.0 from its published release.
- [ ] Bump to 0.1.1, tag `v0.1.1`, publish that release.
- [ ] Start the installed 0.1.0: within a minute the tray shows "Update ready (0.1.1),
      restart" and Settings > Updates shows the same. Restart: the app is 0.1.1.
- [ ] While a Bot is replying, the restart is refused until it has finished.

## Security checklist (docs/09-security.md)

| Item | How it is checked |
|---|---|
| Cross-user access tests pass for every router | `services/tests/test_security_checklist.py` (42 routes, another user and no sign-in) |
| No secret appears in logs during the full test suite | `make check-secrets` |
| Approval cannot be bypassed | `test_approvals.py::test_the_worker_refuses_a_risky_call_without_an_approved_row` |
| `web_fetch` blocks 127.0.0.1, 10.0.0.0/8, 169.254.169.254, file:// | `test_security_checklist.py` and `test_tools.py` |
| Tauri capabilities list only the needed commands | `cargo test` (`capability_allows_nothing_beyond_what_the_app_needs`) |
| CSP set and no inline scripts | `apps/desktop/checks/security.test.ts` |
