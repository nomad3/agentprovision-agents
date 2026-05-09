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
pub async fn login_password(
    client: &ApiClient,
    email: &str,
    password: &str,
) -> Result<Token> {
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
pub async fn poll_device_token(
    client: &ApiClient,
    device_code: &str,
) -> Result<DevicePollOutcome> {
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
}
