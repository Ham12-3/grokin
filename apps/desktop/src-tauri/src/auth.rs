//! Sign-in for the desktop app: PKCE, deep link, keychain, access-token refresh.
//!
//! The refresh token never leaves Rust. JavaScript only ever receives the short-lived
//! access token. Codes and tokens are never logged.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter, State};
use tauri_plugin_opener::OpenerExt;
use url::Url;

use crate::secrets::SecretStore;

const API_PREFIX: &str = "/api/v1";
const DEEP_LINK: &str = "crew://auth";
const DEFAULT_API_URL: &str = "http://localhost:8000";
const REFRESH_TOKEN: &str = "refresh_token";
const DEVICE_ID: &str = "device_id";
/// Refresh this long before the access token really expires.
const EXPIRY_MARGIN: Duration = Duration::from_secs(30);
pub const AUTH_CHANGED: &str = "auth:changed";
pub const AUTH_ERROR: &str = "auth:error";

#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("You are not signed in.")]
    NotSignedIn,
    #[error("Your session has ended. Sign in again.")]
    SessionExpired,
    #[error("Unknown sign-in provider.")]
    InvalidProvider,
    #[error("Enter your email address.")]
    MissingEmail,
    #[error("No sign-in is in progress. Start again from the app.")]
    NoLoginInProgress,
    #[error("Could not reach Crew. Check your connection.")]
    Network,
    #[error("{message}")]
    Api { code: String, message: String },
    #[error("Could not use the system keychain: {0}")]
    Keychain(String),
    #[error("Could not open the browser.")]
    Browser,
}

impl AuthError {
    fn code(&self) -> &str {
        match self {
            Self::NotSignedIn => "not_signed_in",
            Self::SessionExpired => "session_expired",
            Self::InvalidProvider => "invalid_provider",
            Self::MissingEmail => "missing_email",
            Self::NoLoginInProgress => "no_login_in_progress",
            Self::Network => "network",
            Self::Api { code, .. } => code,
            Self::Keychain(_) => "keychain",
            Self::Browser => "browser",
        }
    }
}

/// Commands return `{code, message}` so the UI can show the message and branch on the code.
impl Serialize for AuthError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("AuthError", 2)?;
        state.serialize_field("code", self.code())?;
        state.serialize_field("message", &self.to_string())?;
        state.end()
    }
}

#[derive(Clone, Serialize)]
pub struct Session {
    pub has_session: bool,
}

#[derive(Clone, Serialize)]
struct AuthChanged {
    signed_in: bool,
}

#[derive(Clone, Serialize)]
struct AuthErrorEvent {
    code: String,
    message: String,
}

struct CachedAccess {
    token: String,
    expires_at: Instant,
}

#[derive(Deserialize)]
struct TokenResponse {
    access_token: String,
    refresh_token: String,
    expires_in: u64,
}

#[derive(Deserialize)]
struct ApiErrorBody {
    error: ApiErrorDetail,
}

#[derive(Deserialize)]
struct ApiErrorDetail {
    code: String,
    message: String,
}

pub struct AuthState {
    store: Box<dyn SecretStore>,
    http: reqwest::Client,
    api_base: String,
    /// PKCE verifier for the sign-in in progress. Memory only.
    verifier: Mutex<Option<String>>,
    /// Held across a refresh so two callers never rotate the same refresh token.
    access: tokio::sync::Mutex<Option<CachedAccess>>,
}

/// API base URL: `CREW_API_URL` at run time, else the value compiled in, else localhost.
pub fn resolve_api_base() -> String {
    std::env::var("CREW_API_URL")
        .ok()
        .or_else(|| option_env!("CREW_API_URL").map(str::to_owned))
        .unwrap_or_else(|| DEFAULT_API_URL.to_owned())
        .trim_end_matches('/')
        .to_owned()
}

/// Returns `(verifier, challenge)` for PKCE S256.
pub fn new_pkce() -> (String, String) {
    let mut bytes = [0u8; 48];
    rand::thread_rng().fill_bytes(&mut bytes);
    let verifier = URL_SAFE_NO_PAD.encode(bytes);
    let challenge = pkce_challenge(&verifier);
    (verifier, challenge)
}

pub fn pkce_challenge(verifier: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()))
}

/// Pulls the one-time code out of `crew://auth?code=...`. Anything else is ignored.
pub fn parse_auth_link(url: &Url) -> Option<String> {
    if url.scheme() != "crew" || url.host_str() != Some("auth") {
        return None;
    }
    url.query_pairs()
        .find(|(key, value)| key == "code" && !value.is_empty())
        .map(|(_, value)| value.into_owned())
}

pub fn google_start_url(api_base: &str, challenge: &str) -> Result<Url, AuthError> {
    let mut url = Url::parse(&format!("{api_base}{API_PREFIX}/auth/google/start"))
        .map_err(|_| AuthError::Network)?;
    url.query_pairs_mut()
        .append_pair("redirect", DEEP_LINK)
        .append_pair("code_challenge", challenge);
    Ok(url)
}

fn device_name() -> String {
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "Desktop".to_owned())
}

impl AuthState {
    pub fn new(store: Box<dyn SecretStore>, api_base: String) -> Self {
        Self {
            store,
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(15))
                .build()
                .expect("HTTP client"),
            api_base,
            verifier: Mutex::new(None),
            access: tokio::sync::Mutex::new(None),
        }
    }

    pub fn api_base(&self) -> &str {
        &self.api_base
    }

    pub fn has_session(&self) -> Result<bool, AuthError> {
        Ok(self.refresh_token()?.is_some())
    }

    fn refresh_token(&self) -> Result<Option<String>, AuthError> {
        self.store.get(REFRESH_TOKEN).map_err(AuthError::Keychain)
    }

    fn device_id(&self) -> Result<String, AuthError> {
        if let Some(id) = self.store.get(DEVICE_ID).map_err(AuthError::Keychain)? {
            return Ok(id);
        }
        let id = uuid::Uuid::new_v4().to_string();
        self.store
            .set(DEVICE_ID, &id)
            .map_err(AuthError::Keychain)?;
        Ok(id)
    }

    fn begin_login(&self) -> String {
        let (verifier, challenge) = new_pkce();
        *self.verifier.lock().unwrap() = Some(verifier);
        challenge
    }

    async fn post<T: Serialize>(
        &self,
        path: &str,
        body: &T,
    ) -> Result<reqwest::Response, AuthError> {
        let response = self
            .http
            .post(format!("{}{API_PREFIX}{path}", self.api_base))
            .json(body)
            .send()
            .await
            .map_err(|_| AuthError::Network)?;
        if response.status().is_success() {
            return Ok(response);
        }
        let status = response.status();
        Err(match response.json::<ApiErrorBody>().await {
            Ok(body) => AuthError::Api {
                code: body.error.code,
                message: body.error.message,
            },
            Err(_) => AuthError::Api {
                code: "http_error".into(),
                message: format!("Crew returned an error ({status})."),
            },
        })
    }

    async fn store_tokens(
        &self,
        tokens: TokenResponse,
        cache: &mut Option<CachedAccess>,
    ) -> Result<String, AuthError> {
        // Keychain first: if this fails we must not keep using a rotated-away token.
        self.store
            .set(REFRESH_TOKEN, &tokens.refresh_token)
            .map_err(AuthError::Keychain)?;
        *cache = Some(CachedAccess {
            token: tokens.access_token.clone(),
            expires_at: Instant::now() + Duration::from_secs(tokens.expires_in),
        });
        Ok(tokens.access_token)
    }

    /// Swaps the one-time code from the deep link for tokens.
    pub async fn complete_login(&self, code: &str) -> Result<(), AuthError> {
        let verifier = self
            .verifier
            .lock()
            .unwrap()
            .take()
            .ok_or(AuthError::NoLoginInProgress)?;
        let body = serde_json::json!({
            "code": code,
            "code_verifier": verifier,
            "device_id": self.device_id()?,
            "device_name": device_name(),
        });
        let tokens: TokenResponse = self
            .post("/auth/exchange", &body)
            .await?
            .json()
            .await
            .map_err(|_| AuthError::Network)?;
        let mut cache = self.access.lock().await;
        self.store_tokens(tokens, &mut cache).await?;
        Ok(())
    }

    /// Returns a valid access token, refreshing (and rotating the refresh token) if needed.
    pub async fn access_token(&self, force: bool) -> Result<String, AuthError> {
        let mut cache = self.access.lock().await;
        if !force
            && let Some(cached) = cache.as_ref()
            && cached.expires_at > Instant::now() + EXPIRY_MARGIN
        {
            return Ok(cached.token.clone());
        }
        let refresh_token = self.refresh_token()?.ok_or(AuthError::NotSignedIn)?;
        let body = serde_json::json!({ "refresh_token": refresh_token });
        match self.post("/auth/refresh", &body).await {
            Ok(response) => {
                let tokens: TokenResponse =
                    response.json().await.map_err(|_| AuthError::Network)?;
                self.store_tokens(tokens, &mut cache).await
            }
            Err(AuthError::Api { code, .. }) if code == "invalid_refresh_token" => {
                *cache = None;
                self.store
                    .delete(REFRESH_TOKEN)
                    .map_err(AuthError::Keychain)?;
                Err(AuthError::SessionExpired)
            }
            Err(other) => Err(other),
        }
    }

    /// Clears the local session even if the API cannot be reached.
    pub async fn logout(&self) -> Result<(), AuthError> {
        let mut cache = self.access.lock().await;
        *cache = None;
        let refresh_token = self.refresh_token()?;
        self.store
            .delete(REFRESH_TOKEN)
            .map_err(AuthError::Keychain)?;
        if let Some(token) = refresh_token {
            let body = serde_json::json!({ "refresh_token": token });
            if self.post("/auth/logout", &body).await.is_err() {
                log::warn!("logout: the server could not be told; local session cleared");
            }
        }
        Ok(())
    }
}

fn emit_changed(app: &AppHandle, signed_in: bool) {
    let _ = app.emit(AUTH_CHANGED, AuthChanged { signed_in });
}

/// Called by the deep link handler with the code from `crew://auth?code=...`.
pub async fn handle_login_code(app: &AppHandle, code: String) {
    use tauri::Manager;
    let state = app.state::<AuthState>();
    match state.complete_login(&code).await {
        Ok(()) => {
            log::info!("sign-in completed");
            emit_changed(app, true);
        }
        Err(error) => {
            log::warn!("sign-in failed: {}", error.code());
            let _ = app.emit(
                AUTH_ERROR,
                AuthErrorEvent {
                    code: error.code().to_owned(),
                    message: error.to_string(),
                },
            );
        }
    }
}

#[tauri::command]
pub async fn auth_start_login(
    app: AppHandle,
    state: State<'_, AuthState>,
    provider: String,
    email: Option<String>,
) -> Result<(), AuthError> {
    match provider.as_str() {
        "google" => {
            let challenge = state.begin_login();
            let url = google_start_url(state.api_base(), &challenge)?;
            app.opener()
                .open_url(url.as_str(), None::<&str>)
                .map_err(|_| AuthError::Browser)
        }
        "email" => {
            let email = email
                .map(|e| e.trim().to_owned())
                .filter(|e| !e.is_empty())
                .ok_or(AuthError::MissingEmail)?;
            let challenge = state.begin_login();
            let body = serde_json::json!({ "email": email, "code_challenge": challenge });
            state.post("/auth/email/start", &body).await.map(|_| ())
        }
        _ => Err(AuthError::InvalidProvider),
    }
}

/// Tells the UI whether a session exists. Never returns the refresh token.
#[tauri::command]
pub fn auth_get_tokens(state: State<'_, AuthState>) -> Result<Session, AuthError> {
    Ok(Session {
        has_session: state.has_session()?,
    })
}

#[tauri::command]
pub async fn auth_get_access_token(
    app: AppHandle,
    state: State<'_, AuthState>,
    force: Option<bool>,
) -> Result<String, AuthError> {
    let result = state.access_token(force.unwrap_or(false)).await;
    if matches!(result, Err(AuthError::SessionExpired)) {
        emit_changed(&app, false);
    }
    result
}

#[tauri::command]
pub async fn auth_logout(app: AppHandle, state: State<'_, AuthState>) -> Result<(), AuthError> {
    let result = state.logout().await;
    emit_changed(&app, false);
    result
}

#[tauri::command]
pub fn api_base_url(state: State<'_, AuthState>) -> String {
    state.api_base().to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secrets::memory::MemoryStore;

    fn state() -> AuthState {
        AuthState::new(
            Box::new(MemoryStore::default()),
            "http://localhost:8000".into(),
        )
    }

    #[test]
    fn pkce_matches_rfc_7636_example() {
        assert_eq!(
            pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        );
    }

    #[test]
    fn new_pkce_is_random_and_valid_length() {
        let (verifier_a, challenge_a) = new_pkce();
        let (verifier_b, _) = new_pkce();
        assert_ne!(verifier_a, verifier_b);
        assert_eq!(verifier_a.len(), 64);
        assert_eq!(challenge_a, pkce_challenge(&verifier_a));
    }

    #[test]
    fn parses_auth_deep_link() {
        let url = Url::parse("crew://auth?code=abc-123_X").unwrap();
        assert_eq!(parse_auth_link(&url).as_deref(), Some("abc-123_X"));
    }

    #[test]
    fn ignores_other_links() {
        for link in [
            "crew://auth",
            "crew://auth?code=",
            "crew://other?code=abc",
            "https://auth?code=abc",
            "crew://auth?state=abc",
        ] {
            assert_eq!(parse_auth_link(&Url::parse(link).unwrap()), None, "{link}");
        }
    }

    #[test]
    fn google_url_carries_redirect_and_challenge() {
        let url = google_start_url("http://localhost:8000", "chal").unwrap();
        assert_eq!(url.path(), "/api/v1/auth/google/start");
        let pairs: Vec<(String, String)> = url.query_pairs().into_owned().collect();
        assert_eq!(
            pairs,
            [
                ("redirect".to_owned(), "crew://auth".to_owned()),
                ("code_challenge".to_owned(), "chal".to_owned()),
            ]
        );
    }

    #[test]
    fn session_follows_the_keychain() {
        let state = state();
        assert!(!state.has_session().unwrap());
        state.store.set(REFRESH_TOKEN, "test-only-token").unwrap();
        assert!(state.has_session().unwrap());
    }

    #[test]
    fn device_id_is_created_once() {
        let state = state();
        let first = state.device_id().unwrap();
        assert_eq!(state.device_id().unwrap(), first);
        assert!(uuid::Uuid::parse_str(&first).is_ok());
    }

    #[tokio::test]
    async fn deep_link_without_a_started_login_is_refused() {
        let result = state().complete_login("some-code").await;
        assert!(matches!(result, Err(AuthError::NoLoginInProgress)));
    }

    #[tokio::test]
    async fn access_token_needs_a_session() {
        assert!(matches!(
            state().access_token(false).await,
            Err(AuthError::NotSignedIn)
        ));
    }

    #[tokio::test]
    async fn logout_clears_the_keychain_even_when_offline() {
        // Port 1 refuses connections, so the server call fails.
        let state = AuthState::new(
            Box::new(MemoryStore::default()),
            "http://127.0.0.1:1".into(),
        );
        state.store.set(REFRESH_TOKEN, "test-only-token").unwrap();
        state.logout().await.unwrap();
        assert!(!state.has_session().unwrap());
    }

    #[test]
    fn errors_serialize_as_code_and_message() {
        let json = serde_json::to_value(AuthError::NotSignedIn).unwrap();
        assert_eq!(json["code"], "not_signed_in");
        assert_eq!(json["message"], "You are not signed in.");
    }
}
