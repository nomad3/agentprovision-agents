//! Unified error type for the core crate.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    #[error("API returned {status}: {body}")]
    Api { status: u16, body: String },

    #[error("authentication required")]
    Unauthorized,

    #[error("device-flow login was not authorized in time")]
    DeviceFlowExpired,

    #[error("device-flow login was denied by the user")]
    DeviceFlowDenied,

    #[error("serde error: {0}")]
    Serde(#[from] serde_json::Error),

    #[error("toml parse error: {0}")]
    TomlDe(#[from] toml::de::Error),

    #[error("toml serialize error: {0}")]
    TomlSer(#[from] toml::ser::Error),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("url parse error: {0}")]
    Url(#[from] url::ParseError),

    #[cfg(feature = "keyring")]
    #[error("keychain error: {0}")]
    Keyring(#[from] keyring::Error),

    #[error("invalid configuration: {0}")]
    Config(String),

    #[error("stream ended unexpectedly")]
    StreamEnded,

    #[error("{0}")]
    Other(String),
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub fn other(msg: impl Into<String>) -> Self {
        Error::Other(msg.into())
    }
}
