//! Authentication: token storage + login flows.
//!
//! Token storage is OS-keychain via the `keyring` crate (CLI default). Luna
//! keeps its own storage and does not enable the `keyring` feature; this
//! module still provides the [`TokenStore`] trait so any front-end can plug
//! in its own backend.
//!
//! Login flows:
//! * [`login_password`] — email/password (hits `/api/v1/auth/login`)
//! * [`request_device_code`] / [`poll_device_token`] — device-flow (gh-style).
//!   Requires backend support at `/api/v1/auth/device-code` and
//!   `/api/v1/auth/device-token`. If the endpoints are absent, callers should
//!   fall back to `login_password`.

use serde::{Deserialize, Serialize};
use std::time::Duration;

use crate::client::ApiClient;
use crate::error::{Error, Result};
use crate::models::{DeviceCodeResponse, Token};

/// Trait for pluggable secure-token storage.
pub trait TokenStore: Send + Sync {
    fn load(&self) -> Result<Option<String>>;
    fn save(&self, token: &str) -> Result<()>;
    fn clear(&self) -> Result<()>;
}

/// In-memory token store. Useful for tests and short-lived processes.
#[derive(Default, Debug)]
pub struct MemoryTokenStore {
    inner: std::sync::Mutex<Option<String>>,
}

impl TokenStore for MemoryTokenStore {
    fn load(&self) -> Result<Option<String>> {
        Ok(self.inner.lock().unwrap().clone())
    }
    fn save(&self, token: &str) -> Result<()> {
        *self.inner.lock().unwrap() = Some(token.to_string());
        Ok(())
    }
    fn clear(&self) -> Result<()> {
        *self.inner.lock().unwrap() = None;
        Ok(())
    }
}

/// File-backed token store. Used by:
///   * the `--token-file` flag / `AGENTPROVISION_TOKEN_FILE` env var
///   * the keychain auto-fallback when the keyring backend errors
///     (e.g. headless / SSH session, locked keychain, ACL denial).
///
/// On Unix the file is created with 0600 permissions so other users on a
/// shared box can't snarf the bearer. On Windows we lean on the default
/// per-user ACL inherited from the parent dir.
#[derive(Debug)]
pub struct FileTokenStore {
    path: std::path::PathBuf,
}

impl FileTokenStore {
    pub fn new(path: impl Into<std::path::PathBuf>) -> Self {
        Self { path: path.into() }
    }
}

impl TokenStore for FileTokenStore {
    fn load(&self) -> Result<Option<String>> {
        match std::fs::read_to_string(&self.path) {
            Ok(s) => {
                let trimmed = s.trim();
                if trimmed.is_empty() {
                    Ok(None)
                } else {
                    Ok(Some(trimmed.to_string()))
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(Error::other(format!(
                "failed to read token file {}: {e}",
                self.path.display()
            ))),
        }
    }
    fn save(&self, token: &str) -> Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                Error::other(format!(
                    "failed to create token-file parent {}: {e}",
                    parent.display()
                ))
            })?;
        }
        // Best-effort: chmod 0600 on Unix. On Windows the file inherits
        // the per-user ACL of %USERPROFILE% which is already private.
        #[cfg(unix)]
        {
            use std::io::Write as _;
            use std::os::unix::fs::OpenOptionsExt as _;
            let mut f = std::fs::OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .mode(0o600)
                .open(&self.path)
                .map_err(|e| {
                    Error::other(format!(
                        "failed to open token file {} for write: {e}",
                        self.path.display()
                    ))
                })?;
            f.write_all(token.as_bytes()).map_err(|e| {
                Error::other(format!(
                    "failed to write token file {}: {e}",
                    self.path.display()
                ))
            })?;
        }
        #[cfg(not(unix))]
        {
            std::fs::write(&self.path, token).map_err(|e| {
                Error::other(format!(
                    "failed to write token file {}: {e}",
                    self.path.display()
                ))
            })?;
        }
        Ok(())
    }
    fn clear(&self) -> Result<()> {
        match std::fs::remove_file(&self.path) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(Error::other(format!(
                "failed to remove token file {}: {e}",
                self.path.display()
            ))),
        }
    }
}

/// OS keychain-backed token store. Available with the `keyring` feature.
#[cfg(feature = "keyring")]
pub struct KeyringTokenStore {
    service: String,
    account: String,
}

#[cfg(feature = "keyring")]
impl KeyringTokenStore {
    /// `service` is typically `"agentprovision"`; `account` distinguishes
    /// between profiles or environments (e.g. the API host).
    pub fn new(service: impl Into<String>, account: impl Into<String>) -> Self {
        Self {
            service: service.into(),
            account: account.into(),
        }
    }
    /// Service identifier passed to the OS keyring. Exposed so the CLI can
    /// build a parallel handle for a probe thread.
    pub fn service_str(&self) -> &str {
        &self.service
    }
    /// Account identifier passed to the OS keyring.
    pub fn account_str(&self) -> &str {
        &self.account
    }
    fn entry(&self) -> Result<keyring::Entry> {
        Ok(keyring::Entry::new(&self.service, &self.account)?)
    }
}

#[cfg(feature = "keyring")]
impl TokenStore for KeyringTokenStore {
    fn load(&self) -> Result<Option<String>> {
        match self.entry()?.get_password() {
            Ok(p) => Ok(Some(p)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(Error::Keyring(e)),
        }
    }
    fn save(&self, token: &str) -> Result<()> {
        Ok(self.entry()?.set_password(token)?)
    }
    fn clear(&self) -> Result<()> {
        match self.entry()?.delete_password() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(Error::Keyring(e)),
        }
    }
}

/// Hit `/api/v1/auth/login` with form-encoded credentials.
pub async fn login_password(client: &ApiClient, email: &str, password: &str) -> Result<Token> {
    client.login_password(email, password).await
}

/// Step 1 of device-flow: request a user_code + device_code.
pub async fn request_device_code(client: &ApiClient) -> Result<DeviceCodeResponse> {
    let req = client.request(reqwest::Method::POST, "/api/v1/auth/device-code")?;
    client.send_json(req).await
}

#[derive(Debug, Clone)]
pub enum DevicePollOutcome {
    Pending,
    Approved(Token),
    Denied,
    Expired,
    SlowDown,
}

#[derive(Serialize)]
struct DeviceTokenRequest<'a> {
    device_code: &'a str,
}

#[derive(Deserialize)]
struct DeviceTokenResponse {
    #[serde(default)]
    access_token: Option<String>,
    #[serde(default)]
    token_type: Option<String>,
    #[serde(default)]
    error: Option<String>,
}

/// Step 2 of device-flow: poll for the user's approval. The backend should
/// respond with one of:
/// * 200 + `{access_token, token_type}` when approved
/// * 400 + `{error: "authorization_pending"}` while waiting
/// * 400 + `{error: "slow_down"}` to back off
/// * 400 + `{error: "expired_token"}` when the code expired
/// * 400 + `{error: "access_denied"}` when the user declined
pub async fn poll_device_token(client: &ApiClient, device_code: &str) -> Result<DevicePollOutcome> {
    let req = client
        .request(reqwest::Method::POST, "/api/v1/auth/device-token")?
        .json(&DeviceTokenRequest { device_code });
    let resp = req.send().await?;
    let status = resp.status();
    let body: DeviceTokenResponse = resp.json().await.unwrap_or(DeviceTokenResponse {
        access_token: None,
        token_type: None,
        error: None,
    });
    if status.is_success() {
        if let Some(at) = body.access_token {
            return Ok(DevicePollOutcome::Approved(Token {
                access_token: at,
                token_type: body.token_type.unwrap_or_else(|| "bearer".into()),
            }));
        }
        return Err(Error::other("device-token success without access_token"));
    }
    match body.error.as_deref() {
        Some("authorization_pending") => Ok(DevicePollOutcome::Pending),
        Some("slow_down") => Ok(DevicePollOutcome::SlowDown),
        Some("expired_token") => Ok(DevicePollOutcome::Expired),
        Some("access_denied") => Ok(DevicePollOutcome::Denied),
        Some(other) => Err(Error::Api {
            status: status.as_u16(),
            body: other.to_string(),
        }),
        None => Err(Error::Api {
            status: status.as_u16(),
            body: "unknown device-token error".into(),
        }),
    }
}

/// Convenience: drive the device-flow polling loop to completion.
///
/// `tick` is invoked once per poll with the current outcome — useful for the
/// CLI to render a spinner / message.
pub async fn complete_device_flow<F>(
    client: &ApiClient,
    code: &DeviceCodeResponse,
    mut tick: F,
) -> Result<Token>
where
    F: FnMut(&DevicePollOutcome),
{
    let mut interval = Duration::from_secs(code.interval.max(1));
    let deadline = std::time::Instant::now() + Duration::from_secs(code.expires_in);
    loop {
        if std::time::Instant::now() >= deadline {
            return Err(Error::DeviceFlowExpired);
        }
        tokio::time::sleep(interval).await;
        let outcome = poll_device_token(client, &code.device_code).await?;
        tick(&outcome);
        match outcome {
            DevicePollOutcome::Approved(t) => return Ok(t),
            DevicePollOutcome::Pending => continue,
            DevicePollOutcome::SlowDown => {
                interval += Duration::from_secs(5);
            }
            DevicePollOutcome::Denied => return Err(Error::DeviceFlowDenied),
            DevicePollOutcome::Expired => return Err(Error::DeviceFlowExpired),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memory_token_store_round_trip() {
        let s = MemoryTokenStore::default();
        assert!(s.load().unwrap().is_none());
        s.save("hello").unwrap();
        assert_eq!(s.load().unwrap().as_deref(), Some("hello"));
        s.clear().unwrap();
        assert!(s.load().unwrap().is_none());
    }

    #[test]
    fn file_token_store_round_trip() {
        let dir = std::env::temp_dir().join(format!("agentprovision-test-{}", std::process::id()));
        let path = dir.join("nested").join("token");
        let s = FileTokenStore::new(&path);
        // load on missing file returns Ok(None)
        assert!(s.load().unwrap().is_none());
        // save creates parent dirs
        s.save("bearer-xyz").unwrap();
        assert_eq!(s.load().unwrap().as_deref(), Some("bearer-xyz"));
        // clear removes the file; second clear is a no-op
        s.clear().unwrap();
        assert!(s.load().unwrap().is_none());
        s.clear().unwrap();
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn file_token_store_uses_0600_permissions() {
        use std::os::unix::fs::PermissionsExt;
        let path =
            std::env::temp_dir().join(format!("agentprovision-perm-{}.token", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let s = FileTokenStore::new(&path);
        s.save("bearer").unwrap();
        let mode = std::fs::metadata(&path).unwrap().permissions().mode();
        // Mask to lower 9 bits — `mode()` includes file-type bits on some
        // platforms.
        assert_eq!(mode & 0o777, 0o600, "token file mode = {:o}", mode);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn file_token_store_trims_trailing_whitespace() {
        let path =
            std::env::temp_dir().join(format!("agentprovision-trim-{}.token", std::process::id()));
        std::fs::write(&path, "bearer-abc\n").unwrap();
        let s = FileTokenStore::new(&path);
        assert_eq!(s.load().unwrap().as_deref(), Some("bearer-abc"));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn file_token_store_empty_file_is_none() {
        let path =
            std::env::temp_dir().join(format!("agentprovision-empty-{}.token", std::process::id()));
        std::fs::write(&path, "   \n\n").unwrap();
        let s = FileTokenStore::new(&path);
        assert!(s.load().unwrap().is_none());
        let _ = std::fs::remove_file(&path);
    }
}
