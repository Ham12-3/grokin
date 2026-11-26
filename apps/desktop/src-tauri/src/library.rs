//! "Save to computer" for Library files: ask where, download, write.
//!
//! The window never gets file-system access. It passes a download address; this module
//! accepts it only if it is a Library file on Crew's own API.

use serde::Serialize;
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;

use crate::auth::AuthState;

/// The largest file the Library holds (the API enforces the same limit).
const MAX_BYTES: usize = 20_000_000;

#[derive(Debug, Serialize, PartialEq)]
pub struct SaveError {
    code: &'static str,
    message: &'static str,
}

const NOT_ALLOWED: SaveError = SaveError {
    code: "not_allowed",
    message: "Only files from your Library can be saved.",
};
const DOWNLOAD_FAILED: SaveError = SaveError {
    code: "download_failed",
    message: "The file could not be downloaded. Try again.",
};
const WRITE_FAILED: SaveError = SaveError {
    code: "write_failed",
    message: "The file could not be written there.",
};

/// True only for `<api base>/api/v1/library/<id>/content?...` on the same origin.
pub fn is_library_url(api_base: &str, url: &str) -> bool {
    let prefix = format!("{}/api/v1/library/", api_base.trim_end_matches('/'));
    match url.strip_prefix(&prefix) {
        Some(rest) => {
            let path = rest.split('?').next().unwrap_or("");
            let mut parts = path.split('/');
            let id = parts.next().unwrap_or("");
            !id.is_empty()
                && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-')
                && parts.next() == Some("content")
                && parts.next().is_none()
        }
        None => false,
    }
}

/// A file name with nothing that could move it to another folder.
pub fn safe_name(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|c| match c {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' | '\0' => '_',
            c if c.is_control() => '_',
            c => c,
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').trim();
    if trimmed.is_empty() {
        "file".to_owned()
    } else {
        trimmed.chars().take(120).collect()
    }
}

/// Returns false when the user cancelled the dialog.
#[tauri::command]
pub async fn save_file(
    app: AppHandle,
    state: State<'_, AuthState>,
    url: String,
    filename: String,
) -> Result<bool, SaveError> {
    if !is_library_url(state.api_base(), &url) {
        return Err(NOT_ALLOWED);
    }
    let (sender, receiver) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_file_name(safe_name(&filename))
        .save_file(move |path| {
            let _ = sender.send(path);
        });
    let Some(path) = receiver.await.ok().flatten() else {
        return Ok(false);
    };
    let path = path.into_path().map_err(|_| WRITE_FAILED)?;

    let response = reqwest::get(&url).await.map_err(|_| DOWNLOAD_FAILED)?;
    if !response.status().is_success() {
        return Err(DOWNLOAD_FAILED);
    }
    let bytes = response.bytes().await.map_err(|_| DOWNLOAD_FAILED)?;
    if bytes.len() > MAX_BYTES {
        return Err(DOWNLOAD_FAILED);
    }
    tokio::fs::write(&path, &bytes)
        .await
        .map_err(|_| WRITE_FAILED)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE: &str = "http://localhost:8000";

    #[test]
    fn only_library_files_on_our_api_are_accepted() {
        let good = "http://localhost:8000/api/v1/library/01a2-bc/content?expires=1&sig=ab";
        assert!(is_library_url(BASE, good));
        assert!(is_library_url("http://localhost:8000/", good));
        for bad in [
            "https://evil.example/api/v1/library/01a2/content",
            "http://localhost:8000.evil.example/api/v1/library/01a2/content",
            "http://localhost:8000/api/v1/vault",
            "http://localhost:8000/api/v1/library/../vault/content",
            "http://localhost:8000/api/v1/library/01a2/content/extra",
            "http://localhost:8000/api/v1/library//content",
            "file:///etc/passwd",
        ] {
            assert!(!is_library_url(BASE, bad), "{bad}");
        }
    }

    #[test]
    fn file_names_cannot_leave_the_chosen_folder() {
        assert_eq!(safe_name("report.md"), "report.md");
        assert_eq!(safe_name("../../etc/passwd"), "_.._etc_passwd");
        assert_eq!(safe_name("C:\\Windows\\x.exe"), "C__Windows_x.exe");
        assert_eq!(safe_name("  ..  "), "file");
        assert_eq!(safe_name(""), "file");
    }
}
