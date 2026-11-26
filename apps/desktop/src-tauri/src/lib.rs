//! Crew desktop core. OS jobs only (keychain, deep links, tray, notifications, updater).
//! Business logic lives in the backend. Every command must be listed in `build.rs` and in
//! `capabilities/default.json`.

mod auth;
mod library;
mod secrets;
mod tray;
mod updater;

use tauri::{Manager, WindowEvent};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_window_state::StateFlags;

#[tauri::command]
fn app_version(app: tauri::AppHandle) -> String {
    app.package_info().version.to_string()
}

/// Shows a desktop notification unless the user is already looking at Crew.
/// Returns whether one was shown.
#[tauri::command]
fn notify(app: tauri::AppHandle, title: String, body: String) -> bool {
    use tauri_plugin_notification::NotificationExt;

    let (visible, focused) = app
        .get_webview_window("main")
        .map(|window| {
            (
                window.is_visible().unwrap_or(false),
                window.is_focused().unwrap_or(false),
            )
        })
        .unwrap_or((false, false));
    if !tray::should_notify(visible, focused) {
        return false;
    }
    let title: String = title.chars().take(120).collect();
    let body: String = body.chars().take(300).collect();
    match app.notification().builder().title(title).body(body).show() {
        Ok(()) => {
            tray::remember_notification(&app);
            true
        }
        Err(error) => {
            log::warn!("could not show a notification: {error}");
            false
        }
    }
}

/// Pending approvals count for the tray tooltip and menu.
#[tauri::command]
fn set_tray_badge(app: tauri::AppHandle, count: u32) {
    tray::set_badge(&app, count);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    // Must be the first plugin: a second launch (for example from a crew:// link) hands
    // its arguments to the running app and exits. The deep-link feature forwards the link.
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            tray::show_main_window(app);
        }));
    }

    builder
        .plugin(tauri_plugin_deep_link::init())
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(updater::UpdateState::default())
        .plugin(tauri_plugin_opener::init())
        .plugin(
            // Do not restore "hidden": the app hides to the tray on close.
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::all() & !StateFlags::VISIBLE)
                .build(),
        )
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(auth::AuthState::new(
            Box::new(secrets::KeyringStore),
            auth::resolve_api_base(),
        ))
        .setup(|app| {
            // Installed builds register crew:// through the installer. In dev, and for
            // Linux AppImages, register it at run time.
            #[cfg(any(windows, target_os = "linux"))]
            if let Err(error) = app.deep_link().register_all() {
                log::warn!("could not register the crew:// link handler: {error}");
            }

            let handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    // Never log the URL: it carries a one-time sign-in code.
                    if let Some(code) = auth::parse_auth_link(&url) {
                        let handle = handle.clone();
                        tray::show_main_window(&handle);
                        tauri::async_runtime::spawn(async move {
                            auth::handle_login_code(&handle, code).await;
                        });
                    }
                }
            });

            tray::create(app.handle())?;
            updater::start(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                WindowEvent::CloseRequested { api, .. } => {
                    // Keep running in the tray so notifications still arrive.
                    api.prevent_close();
                    let _ = window.hide();
                }
                WindowEvent::Focused(true) => tray::window_focused(window.app_handle()),
                _ => {}
            }
        })
        .invoke_handler(tauri::generate_handler![
            auth::auth_start_login,
            auth::auth_get_tokens,
            auth::auth_get_access_token,
            auth::auth_logout,
            auth::api_base_url,
            app_version,
            notify,
            set_tray_badge,
            library::save_file,
            updater::update_status,
            updater::update_restart,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Crew");
}

#[cfg(test)]
mod tests {
    /// Commands declared in build.rs. Each needs an `allow-...` line in the capability.
    const COMMANDS: [&str; 11] = [
        "auth_start_login",
        "auth_get_tokens",
        "auth_get_access_token",
        "auth_logout",
        "api_base_url",
        "app_version",
        "notify",
        "set_tray_badge",
        "save_file",
        "update_status",
        "update_restart",
    ];

    fn permissions() -> Vec<String> {
        let raw = include_str!("../capabilities/default.json");
        let cap: serde_json::Value = serde_json::from_str(raw).expect("valid JSON");
        assert_eq!(cap["windows"], serde_json::json!(["main"]));
        cap["permissions"]
            .as_array()
            .expect("permissions array")
            .iter()
            .map(|p| p.as_str().expect("string permission").to_owned())
            .collect()
    }

    #[test]
    fn every_command_is_listed_in_the_capability() {
        let perms = permissions();
        for command in COMMANDS {
            let permission = format!("allow-{}", command.replace('_', "-"));
            assert!(perms.contains(&permission), "missing {permission}");
        }
    }

    #[test]
    fn capability_allows_nothing_beyond_what_the_app_needs() {
        let mut expected: Vec<String> = COMMANDS
            .iter()
            .map(|c| format!("allow-{}", c.replace('_', "-")))
            .collect();
        expected.extend(
            [
                "core:default",
                "deep-link:default",
                "notification:default",
                "dialog:allow-save",
                "store:default",
                "opener:default",
                "window-state:default",
                "autostart:default",
                "log:default",
            ]
            .map(str::to_owned),
        );
        let mut actual = permissions();
        actual.sort();
        expected.sort();
        assert_eq!(actual, expected);
        assert!(
            !actual
                .iter()
                .any(|p| p.starts_with("fs:") || p.starts_with("shell:"))
        );
    }
}
