# Phase 11 (optional): Local bridge

Build phase 11 only. Read `docs/04-desktop-tauri.md` (Local bridge).

## Build

1. Settings > Local computer: pick allowed folders (Tauri dialog), list them, remove them.
2. Rust commands `bridge_list_dir`, `bridge_read_file` (max 5 MB), `bridge_write_file` (new files only unless the user allows overwrite), `bridge_run` (off by default; separate toggle). Each checks the path is inside an allowed folder after resolving symlinks.
3. Every call shows a native dialog: Allow once / Always allow for this folder / Deny. Remember "always" per folder in the store plugin.
4. Backend tools `local_list`, `local_read`, `local_write`, `local_run` send `bridge.request` over the user's WebSocket and wait up to 60s for `bridge.response`. If the app is offline: "Your computer is not connected".
5. `local_write` and `local_run` are risky (approval first, then the native dialog).
6. Tests: path escape attempts (`..`, symlinks) are refused; offline path; timeout.

## Done means

- A Bot lists and reads a file from an allowed folder after you click Allow.
- A path outside allowed folders is refused without a dialog.
- With the app quit, the Bot says your computer is not connected.

Update PROGRESS.md, give manual test steps, suggest a commit, then stop.
