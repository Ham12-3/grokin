fn main() {
    // Declaring the commands here makes Tauri require an explicit `allow-<command>`
    // permission in capabilities/default.json for each one.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "auth_start_login",
            "auth_get_tokens",
            "auth_get_access_token",
            "auth_logout",
            "api_base_url",
            "app_version",
        ]),
    ))
    .expect("failed to run tauri-build");
}
