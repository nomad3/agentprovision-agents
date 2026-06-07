//! Unified error type for the core crate.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    // Transport classification (PR-A2 item 3).
    // The old single `Http(#[from] reqwest::Error)` variant collapsed
    // offline/connect, request timeout, and mid-stream transport drops into
    // one bucket, so callers could not decide whether a failure was worth
    // retrying. We now split the common reqwest failure modes into typed
    // variants via a classifying `From<reqwest::Error>` impl (below) while
    // keeping `Http` as the fallback. `Error::kind()` / `Error::is_retryable()`
    // give callers (the CLI reconnect loop) a stable branch surface.
    /// Could not reach the server: connection refused, DNS failure, offline.
    #[error("cannot reach server (offline or connection refused): {0}")]
    Offline(#[source] reqwest::Error),

    /// The request exceeded the client timeout.
    #[error("request timed out: {0}")]
    Timeout(#[source] reqwest::Error),

    /// Transport/body stream interrupted mid-flight (drop, reset, broken pipe).
    #[error("transport error (stream interrupted): {0}")]
    Transport(#[source] reqwest::Error),

    /// Any other reqwest failure (decode, builder, redirect) we don't classify.
    #[error("HTTP error: {0}")]
    Http(#[source] reqwest::Error),

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

/// Coarse transport category, used by callers to branch retry-vs-surface
/// without matching on every concrete variant. Stable contract for the CLI
/// reconnect loop (PR-A2).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorKind {
    /// Server unreachable (connect refused / DNS / offline).
    Offline,
    /// Request timed out.
    Timeout,
    /// Transport/body stream interrupted mid-flight.
    Transport,
    /// SSE/stream ended without a terminal frame.
    StreamEnded,
    /// API responded 4xx.
    ApiClient,
    /// API responded 5xx.
    ApiServer,
    /// Logical / terminal failure that retrying cannot fix (auth, config).
    Terminal,
    /// Everything else (serde, io, unclassified).
    Other,
}

impl Error {
    pub fn other(msg: impl Into<String>) -> Self {
        Error::Other(msg.into())
    }

    /// Coarse category for retry/branch decisions. See [`ErrorKind`].
    pub fn kind(&self) -> ErrorKind {
        match self {
            Error::Offline(_) => ErrorKind::Offline,
            Error::Timeout(_) => ErrorKind::Timeout,
            Error::Transport(_) => ErrorKind::Transport,
            Error::StreamEnded => ErrorKind::StreamEnded,
            Error::Api { status, .. } if (500..600).contains(status) => ErrorKind::ApiServer,
            Error::Api { status, .. } if (400..500).contains(status) => ErrorKind::ApiClient,
            Error::Unauthorized
            | Error::DeviceFlowExpired
            | Error::DeviceFlowDenied
            | Error::Config(_) => ErrorKind::Terminal,
            _ => ErrorKind::Other,
        }
    }

    /// Whether retrying the same operation could plausibly succeed. Transient
    /// transport failures and 5xx are retryable; 4xx is not, except 408
    /// (request timeout) and 429 (rate limited). Logical/terminal failures and
    /// unclassified errors are not retryable.
    pub fn is_retryable(&self) -> bool {
        match self.kind() {
            ErrorKind::Offline
            | ErrorKind::Timeout
            | ErrorKind::Transport
            | ErrorKind::StreamEnded
            | ErrorKind::ApiServer => true,
            ErrorKind::ApiClient => {
                matches!(self, Error::Api { status, .. } if *status == 408 || *status == 429)
            }
            ErrorKind::Terminal | ErrorKind::Other => false,
        }
    }
}

/// Classify a `reqwest::Error` into a typed transport variant. Order matters:
/// connect and timeout are checked before the broader `is_request()` because
/// reqwest reports them as request-related too.
impl From<reqwest::Error> for Error {
    fn from(e: reqwest::Error) -> Self {
        if e.is_connect() {
            Error::Offline(e)
        } else if e.is_timeout() {
            Error::Timeout(e)
        } else if e.is_body() || e.is_request() {
            // is_body: response-body/stream failure mid-flight (drop, reset).
            // is_request: failure building or sending the request.
            Error::Transport(e)
        } else {
            // decode, redirect, builder, and anything else we don't classify.
            Error::Http(e)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn api(status: u16) -> Error {
        Error::Api {
            status,
            body: String::new(),
        }
    }

    #[test]
    fn api_4xx_is_client_and_not_retryable() {
        assert_eq!(api(404).kind(), ErrorKind::ApiClient);
        assert!(!api(404).is_retryable());
        assert_eq!(api(400).kind(), ErrorKind::ApiClient);
        assert!(!api(403).is_retryable());
    }

    #[test]
    fn api_5xx_is_server_and_retryable() {
        assert_eq!(api(500).kind(), ErrorKind::ApiServer);
        assert!(api(500).is_retryable());
        assert!(api(503).is_retryable());
    }

    #[test]
    fn api_408_and_429_are_retryable() {
        assert!(api(408).is_retryable());
        assert!(api(429).is_retryable());
    }

    #[test]
    fn stream_ended_is_retryable() {
        assert_eq!(Error::StreamEnded.kind(), ErrorKind::StreamEnded);
        assert!(Error::StreamEnded.is_retryable());
    }

    #[test]
    fn auth_and_config_are_terminal_not_retryable() {
        assert_eq!(Error::Unauthorized.kind(), ErrorKind::Terminal);
        assert!(!Error::Unauthorized.is_retryable());
        assert_eq!(Error::DeviceFlowDenied.kind(), ErrorKind::Terminal);
        assert!(!Error::Config("bad".into()).is_retryable());
    }

    #[test]
    fn other_is_not_retryable() {
        assert_eq!(Error::other("boom").kind(), ErrorKind::Other);
        assert!(!Error::other("boom").is_retryable());
    }
}
