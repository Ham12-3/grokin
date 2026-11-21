//! Crew desktop core. OS jobs only (keychain, deep links, tray, notifications, updater).
//! Business logic lives in the backend. Commands arrive from phase 1; every one must be
//! listed in `capabilities/default.json`.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("error while running Crew");
}

#[cfg(test)]
mod tests {
    #[test]
    fn default_capability_allows_only_installed_plugins() {
        let raw = include_str!("../capabilities/default.json");
        let cap: serde_json::Value = serde_json::from_str(raw).expect("valid JSON");
        let perms: Vec<&str> = cap["permissions"]
            .as_array()
            .expect("permissions array")
            .iter()
            .filter_map(|p| p.as_str())
            .collect();
        assert_eq!(perms, ["core:default", "opener:default"]);
        assert_eq!(cap["windows"], serde_json::json!(["main"]));
    }
}
