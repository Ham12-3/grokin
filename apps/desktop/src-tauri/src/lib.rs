//! Crew desktop core. OS jobs only (keychain, deep links, tray, notifications, updater).
//! Business logic lives in the backend. Every command must be listed in `build.rs` and in
//! `capabilities/default.json`.

mod auth;
mod secrets;
mod tray;

use tauri::WindowEvent;
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_window_state::StateFlags;

#[tauri::command]
fn app_version(app: tauri::AppHandle) -> String {
    app.package_info().version.to_string()
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
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Keep running in the tray so notifications still arrive.
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            auth::auth_start_login,
            auth::auth_get_tokens,
            auth::auth_get_access_token,
            auth::auth_logout,
            auth::api_base_url,
            app_version,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Crew");
}

#[cfg(test)]
mod tests {
    /// Commands declared in build.rs. Each needs an `allow-...` line in the capability.
    const COMMANDS: [&str; 6] = [
        "auth_start_login",
        "auth_get_tokens",
        "auth_get_access_token",
        "auth_logout",
        "api_base_url",
        "app_version",
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
    fn capability_allows_nothing_beyond_what_phase_1_needs() {
        let mut expected: Vec<String> = COMMANDS
            .iter()
            .map(|c| format!("allow-{}", c.replace('_', "-")))
            .collect();
        expected.extend(
            [
                "core:default",
                "deep-link:default",
                "notification:default",
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
