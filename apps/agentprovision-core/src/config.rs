//! Configuration file: `~/.config/agentprovision/config.toml`.
//!
//! Stores non-secret preferences:
//! * `server` — API base URL
//! * `tenant_id` — default tenant override
//! * `default_agent` — default agent slug for `chat`
//! * `aliases` — llm-style command aliases
//!
//! Tokens are NOT stored here. They live in the OS keychain via [`crate::auth`].

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::client::DEFAULT_BASE_URL;
use crate::error::{Error, Result};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    #[serde(default = "default_server")]
    pub server: String,
    #[serde(default)]
    pub tenant_id: Option<String>,
    #[serde(default)]
    pub default_agent: Option<String>,
    #[serde(default)]
    pub aliases: BTreeMap<String, String>,
}

fn default_server() -> String {
    DEFAULT_BASE_URL.into()
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server: default_server(),
            tenant_id: None,
            default_agent: None,
            aliases: BTreeMap::new(),
        }
    }
}

/// Resolve the config file path. Honours `AGENTPROVISION_CONFIG` env var.
pub fn config_path() -> Result<PathBuf> {
    if let Ok(p) = std::env::var("AGENTPROVISION_CONFIG") {
        return Ok(PathBuf::from(p));
    }
    let dir = dirs::config_dir().ok_or_else(|| Error::Config("no XDG config dir".into()))?;
    Ok(dir.join("agentprovision").join("config.toml"))
}

pub fn load() -> Result<Config> {
    load_from(&config_path()?)
}

pub fn load_from(path: &Path) -> Result<Config> {
    if !path.exists() {
        return Ok(Config::default());
    }
    let raw = std::fs::read_to_string(path)?;
    if raw.trim().is_empty() {
        return Ok(Config::default());
    }
    Ok(toml::from_str(&raw)?)
}

pub fn save(config: &Config) -> Result<()> {
    save_to(config, &config_path()?)
}

pub fn save_to(config: &Config, path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let raw = toml::to_string_pretty(config)?;
    std::fs::write(path, raw)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn round_trip() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("config.toml");
        let mut c = Config::default();
        c.server = "https://example.com".into();
        c.tenant_id = Some("tnt-123".into());
        c.aliases.insert("ls".into(), "agent ls".into());
        save_to(&c, &path).unwrap();
        let loaded = load_from(&path).unwrap();
        assert_eq!(loaded.server, "https://example.com");
        assert_eq!(loaded.tenant_id.as_deref(), Some("tnt-123"));
        assert_eq!(loaded.aliases.get("ls").unwrap(), "agent ls");
    }

    #[test]
    fn missing_file_returns_default() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("nope.toml");
        let c = load_from(&path).unwrap();
        assert_eq!(c.server, DEFAULT_BASE_URL);
    }
}
