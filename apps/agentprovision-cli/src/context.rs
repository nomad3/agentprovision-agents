//! Run-time context shared across subcommands.
//!
//! Holds the resolved configuration, the OS-keychain-backed token store, an
//! `ApiClient` already loaded with the saved token (if any), and the global
//! flag echo (`--json`, `--no-stream`).

use std::sync::Arc;

use agentprovision_core::auth::{FileTokenStore, KeyringTokenStore, TokenStore};
use agentprovision_core::client::{ApiClient, DEFAULT_BASE_URL};
use agentprovision_core::config::{self, Config};

use crate::cli::Cli;

const KEYRING_SERVICE: &str = "agentprovision";

/// Probe the keychain backend with a non-mutating `load()`. macOS pops a
/// Security Agent dialog the first time an unsigned binary touches a given
/// keychain item; in headless contexts (CI, SSH, no-GUI) that prompt has
/// nobody to dismiss it and the process hangs forever. We give the probe
/// 1.5s — local keychain reads on a healthy session return in <50ms.
fn keychain_works(store: &KeyringTokenStore) -> bool {
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    // SAFETY: the probe doesn't mutate the keychain — `load()` is read-only
    // and returns `Ok(None)` cleanly when no entry exists.
    let (tx, rx) = mpsc::channel();
    // Move a fresh handle into the worker thread so we don't have to bound
    // the lifetime of `store`.
    let probe = KeyringTokenStore::new(store.service_str(), store.account_str());
    thread::spawn(move || {
        let _ = tx.send(probe.load().is_ok());
    });
    rx.recv_timeout(Duration::from_millis(1500))
        .unwrap_or(false)
}

/// Tag describing which token-store backend `Context` resolved to. Used to
/// keep user-facing messages honest ("saved to OS keychain" vs "saved to
/// /path/to/file") and to surface this in `status --json` for scripts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenStoreKind {
    Keychain,
    File,
}

impl TokenStoreKind {
    pub fn human(&self) -> &'static str {
        match self {
            TokenStoreKind::Keychain => "OS keychain",
            TokenStoreKind::File => "token file",
        }
    }
}

pub struct Context {
    // `config` + `config_path` + `save_config` are used by PR-C's `config`
    // subcommand; pre-loaded here so subcommands don't each re-parse the
    // file. Marked `allow(dead_code)` until that PR lands.
    #[allow(dead_code)]
    pub config: Config,
    #[allow(dead_code)]
    pub config_path: std::path::PathBuf,
    pub client: ApiClient,
    pub token_store: Arc<dyn TokenStore>,
    pub token_store_kind: TokenStoreKind,
    pub server: String,
    pub json: bool,
    pub no_stream: bool,
}

impl Context {
    pub async fn new(args: &Cli) -> anyhow::Result<Self> {
        let config_path = config::config_path()?;
        let mut cfg = config::load_from(&config_path)?;
        // Honour --server override for this invocation only. The `--tenant`
        // flag was removed (PR #332 review Critical #3); `cfg.tenant_id`
        // still loads from config.toml so PR-C can light up the override
        // alongside the first MCP-bound subcommand.
        if let Some(s) = &args.server {
            cfg.server = s.clone();
        } else if cfg.server.is_empty() {
            cfg.server = DEFAULT_BASE_URL.into();
        }

        // Token-store selection (in priority order):
        //   1. AGENTPROVISION_TOKEN_FILE env var → explicit file store
        //   2. OS keychain, IF a 1.5s probe returns within the deadline
        //   3. fallback file store at $XDG_DATA_HOME/agentprovision/token
        // This keeps the secure-by-default keychain path for desktop users
        // while making the CLI usable in CI / SSH / locked-keychain
        // environments where the macOS Security Agent prompt has no GUI to
        // dismiss it. (Discovered during E2E testing — every rebuild hashes
        // a "new" binary and the keychain ACL prompt hangs the process.)
        let (token_store, token_store_kind): (Arc<dyn TokenStore>, TokenStoreKind) =
            if let Ok(p) = std::env::var("AGENTPROVISION_TOKEN_FILE") {
                log::info!("token-store: file (AGENTPROVISION_TOKEN_FILE)");
                (Arc::new(FileTokenStore::new(p)), TokenStoreKind::File)
            } else {
                let kr = KeyringTokenStore::new(KEYRING_SERVICE, account_for(&cfg.server));
                if keychain_works(&kr) {
                    log::info!("token-store: OS keychain");
                    (Arc::new(kr), TokenStoreKind::Keychain)
                } else {
                    let path = fallback_token_path(&cfg.server)?;
                    log::info!(
                        "token-store: file fallback at {} (keychain unresponsive)",
                        path.display()
                    );
                    (Arc::new(FileTokenStore::new(path)), TokenStoreKind::File)
                }
            };

        let client = ApiClient::new(&cfg.server)?;
        if let Some(token) = token_store.load()? {
            client.set_token(Some(token));
        }
        if let Some(t) = cfg.tenant_id.clone() {
            client.set_tenant_id(Some(t));
        }

        Ok(Self {
            server: cfg.server.clone(),
            config: cfg,
            config_path,
            client,
            token_store,
            token_store_kind,
            json: args.json,
            no_stream: args.no_stream,
        })
    }

    #[allow(dead_code)]
    pub fn save_config(&self) -> anyhow::Result<()> {
        config::save_to(&self.config, &self.config_path)?;
        Ok(())
    }
}

/// The keychain account string distinguishes between profiles / environments.
/// Using the host portion of the server URL keeps prod and self-hosted
/// tokens separate.
fn account_for(server: &str) -> String {
    match url::Url::parse(server) {
        Ok(u) => u.host_str().unwrap_or(server).to_string(),
        Err(_) => server.to_string(),
    }
}

/// Per-server token file path used when the keychain backend is unusable.
/// Lives in the user's data dir to keep `~/.config` clean — the file holds
/// a bearer, not a config value.
fn fallback_token_path(server: &str) -> anyhow::Result<std::path::PathBuf> {
    let base = dirs::data_local_dir()
        .or_else(dirs::data_dir)
        .ok_or_else(|| anyhow::anyhow!("could not determine user data directory"))?;
    Ok(base
        .join("agentprovision")
        .join("tokens")
        .join(format!("{}.token", account_for(server))))
}
