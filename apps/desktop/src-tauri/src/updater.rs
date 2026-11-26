//! App updates: check on start and every 6 hours, download quietly, and install only when
//! the window asks for a restart (it never asks while a Bot is replying).

use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

use crate::tray;

const CHECK_EVERY: Duration = Duration::from_secs(6 * 60 * 60);
/// Sent to the window when an update has been downloaded. Payload: the new version.
pub const READY_EVENT: &str = "update:ready";
/// Sent when the tray's "Update ready, restart" is clicked: the window decides when.
pub const RESTART_REQUESTED_EVENT: &str = "update:restart-requested";

/// A downloaded update waiting for a restart.
#[derive(Default)]
pub struct UpdateState {
    ready: Mutex<Option<(Update, Vec<u8>)>>,
}

impl UpdateState {
    fn version(&self) -> Option<String> {
        self.ready
            .lock()
            .ok()?
            .as_ref()
            .map(|(update, _)| update.version.clone())
    }
}

async fn check(app: &AppHandle) {
    let state = app.state::<UpdateState>();
    if state.version().is_some() {
        return; // one is already waiting
    }
    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(error) => {
            log::warn!("updates are not set up: {error}");
            return;
        }
    };
    let update = match updater.check().await {
        Ok(Some(update)) => update,
        Ok(None) => return,
        Err(error) => {
            log::info!("could not check for updates: {error}");
            return;
        }
    };
    // Download now (the signature is verified), install later.
    let bytes = match update.download(|_, _| {}, || {}).await {
        Ok(bytes) => bytes,
        Err(error) => {
            log::warn!("could not download the update: {error}");
            return;
        }
    };
    let version = update.version.clone();
    if let Ok(mut ready) = state.ready.lock() {
        *ready = Some((update, bytes));
    }
    tray::set_update_ready(app, &version);
    let _ = app.emit(READY_EVENT, version);
}

/// Starts the background checks. Call once at start-up.
pub fn start(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            check(&app).await;
            tokio::time::sleep(CHECK_EVERY).await;
        }
    });
}

/// The version that is downloaded and waiting, if any.
#[tauri::command]
pub fn update_status(state: tauri::State<'_, UpdateState>) -> Option<String> {
    state.version()
}

/// Installs the downloaded update and restarts. The window calls this only when no Bot is
/// in the middle of a reply.
#[tauri::command]
pub fn update_restart(app: AppHandle, state: tauri::State<'_, UpdateState>) -> bool {
    let taken = state.ready.lock().ok().and_then(|mut ready| ready.take());
    let Some((update, bytes)) = taken else {
        return false;
    };
    if let Err(error) = update.install(bytes) {
        log::warn!("could not install the update: {error}");
        return false;
    }
    app.restart();
}
