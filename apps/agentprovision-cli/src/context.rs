//! Run-time context shared across subcommands.
//!
//! Holds the resolved configuration, the OS-keychain-backed token store, an
//! `ApiClient` already loaded with the saved token (if any), and the global
//! flag echo (`--json`, `--no-stream`).

use std::sync::Arc;

use agentprovision_core::auth::{KeyringTokenStore, TokenStore};
use agentprovision_core::client::{ApiClient, DEFAULT_BASE_URL};
use agentprovision_core::config::{self, Config};

use crate::cli::Cli;

const KEYRING_SERVICE: &str = "agentprovision";

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
    pub server: String,
    pub json: bool,
    pub no_stream: bool,
}

impl Context {
    pub async fn new(args: &Cli) -> anyhow::Result<Self> {
        let config_path = config::config_path()?;
        let mut cfg = config::load_from(&config_path)?;
        // Honour --tenant / --server overrides for this invocation only.
        if let Some(s) = &args.server {
            cfg.server = s.clone();
        } else if cfg.server.is_empty() {
            cfg.server = DEFAULT_BASE_URL.into();
        }
        if let Some(t) = &args.tenant {
            cfg.tenant_id = Some(t.clone());
        }

        let token_store: Arc<dyn TokenStore> =
            Arc::new(KeyringTokenStore::new(KEYRING_SERVICE, account_for(&cfg.server)));

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
