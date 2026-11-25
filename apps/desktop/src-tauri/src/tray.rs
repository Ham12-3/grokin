//! Tray icon and menu. Closing the window hides it here; Quit really exits.
//! The menu and tooltip show how many approvals are waiting.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Wry};

const OPEN: &str = "open";
const APPROVALS: &str = "approvals";
const QUIT: &str = "quit";
const TRAY_ID: &str = "main";
/// Tells the window to show the Approvals screen.
pub const OPEN_APPROVALS_EVENT: &str = "open:approvals";

/// Kept in app state so the count can change after the menu is built.
pub struct TrayState {
    approvals: MenuItem<Wry>,
    /// Set when a notification was shown: the next time the window comes to the front it
    /// opens the Approvals screen.
    open_approvals_on_focus: AtomicBool,
}

pub fn approvals_label(count: u32) -> String {
    format!("Pending approvals ({count})")
}

pub fn tooltip(count: u32) -> String {
    match count {
        0 => "Crew".to_owned(),
        1 => "Crew: 1 approval waiting".to_owned(),
        n => format!("Crew: {n} approvals waiting"),
    }
}

/// A notification is only useful when the user is not already looking at Crew.
pub fn should_notify(visible: bool, focused: bool) -> bool {
    !(visible && focused)
}

pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn open_approvals(app: &AppHandle) {
    show_main_window(app);
    if let Some(state) = app.try_state::<TrayState>() {
        state.open_approvals_on_focus.store(false, Ordering::SeqCst);
    }
    let _ = app.emit(OPEN_APPROVALS_EVENT, ());
}

/// Called after a notification is shown.
pub fn remember_notification(app: &AppHandle) {
    if let Some(state) = app.try_state::<TrayState>() {
        state.open_approvals_on_focus.store(true, Ordering::SeqCst);
    }
}

/// Called when the main window comes to the front.
pub fn window_focused(app: &AppHandle) {
    if let Some(state) = app.try_state::<TrayState>()
        && state.open_approvals_on_focus.swap(false, Ordering::SeqCst)
    {
        let _ = app.emit(OPEN_APPROVALS_EVENT, ());
    }
}

pub fn set_badge(app: &AppHandle, count: u32) {
    if let Some(state) = app.try_state::<TrayState>() {
        let _ = state.approvals.set_text(approvals_label(count));
        if count == 0 {
            // Nothing left to open.
            state.open_approvals_on_focus.store(false, Ordering::SeqCst);
        }
    }
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(tooltip(count)));
    }
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, OPEN, "Open Crew", true, None::<&str>)?;
    let approvals = MenuItem::with_id(app, APPROVALS, approvals_label(0), true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT, "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &approvals, &quit])?;
    app.manage(TrayState {
        approvals,
        open_approvals_on_focus: AtomicBool::new(false),
    });

    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip(tooltip(0))
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            OPEN => show_main_window(app),
            APPROVALS => open_approvals(app),
            QUIT => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn labels_show_the_count() {
        assert_eq!(approvals_label(0), "Pending approvals (0)");
        assert_eq!(approvals_label(3), "Pending approvals (3)");
        assert_eq!(tooltip(0), "Crew");
        assert_eq!(tooltip(1), "Crew: 1 approval waiting");
        assert_eq!(tooltip(4), "Crew: 4 approvals waiting");
    }

    #[test]
    fn notifies_only_when_the_user_is_not_looking() {
        assert!(!should_notify(true, true));
        assert!(should_notify(true, false)); // behind another window
        assert!(should_notify(false, false)); // hidden in the tray
        assert!(should_notify(false, true));
    }
}
