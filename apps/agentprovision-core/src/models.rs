//! Serde models matching the AgentProvision API schemas.
//!
//! Only the fields the CLI / Luna actually read are modelled today; new fields
//! can be added freely because everything uses `#[serde(default)]` and
//! `serde_json::Value` for unknown extras.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fmt;
use uuid::Uuid;

#[derive(Clone, Serialize, Deserialize)]
pub struct Token {
    pub access_token: String,
    #[serde(default = "default_token_type")]
    pub token_type: String,
}

// PR #332 review Critical #1 fix: never let the bearer token print
// through the default `#[derive(Debug)]` impl — even with -vv on the
// CLI, the only thing log lines should ever see is `Token { access_token: <redacted>, .. }`.
impl fmt::Debug for Token {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Token")
            .field("access_token", &"<redacted>")
            .field("token_type", &self.token_type)
            .finish()
    }
}

fn default_token_type() -> String {
    "bearer".into()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    #[serde(default)]
    pub full_name: Option<String>,
    #[serde(default)]
    pub tenant_id: Option<Uuid>,
    #[serde(default)]
    pub is_superuser: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tenant {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub slug: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatSession {
    pub id: Uuid,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub agent_id: Option<Uuid>,
    #[serde(default)]
    pub created_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub id: Option<Uuid>,
    pub role: String,
    pub content: String,
    #[serde(default)]
    pub created_at: Option<DateTime<Utc>>,
}

/// Request body for `POST /api/v1/chat/sessions/{id}/messages`.
#[derive(Debug, Clone, Serialize)]
pub struct ChatMessageRequest<'a> {
    pub content: &'a str,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatTurn {
    /// The user's message in this turn. Backend serialises as `user_message`;
    /// `user` is kept as an alias for older payloads.
    #[serde(rename = "user_message", alias = "user")]
    pub user: ChatMessage,
    /// The assistant's reply.
    #[serde(rename = "assistant_message", alias = "assistant")]
    pub assistant: ChatMessage,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session: Option<ChatSession>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Workflow {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowRun {
    pub id: Uuid,
    #[serde(default)]
    pub workflow_id: Option<Uuid>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub started_at: Option<DateTime<Utc>>,
    #[serde(default)]
    pub finished_at: Option<DateTime<Utc>>,
}

/// Device-flow login response. Mirrors GitHub's device-flow shape.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceCodeResponse {
    pub device_code: String,
    pub user_code: String,
    pub verification_uri: String,
    #[serde(default)]
    pub verification_uri_complete: Option<String>,
    pub expires_in: u64,
    #[serde(default = "default_interval")]
    pub interval: u64,
}

fn default_interval() -> u64 {
    5
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Locks down the Critical #1 fix: a Token must never expose its
    /// `access_token` through `Debug` formatting. If a future refactor
    /// re-derives `Debug` on `Token`, this test fails.
    #[test]
    fn token_debug_redacts_access_token() {
        let t = Token {
            access_token: "very-secret-bearer-1234567890".into(),
            token_type: "bearer".into(),
        };
        let dbg = format!("{t:?}");
        assert!(
            !dbg.contains("very-secret-bearer"),
            "Token Debug leaked access_token: {dbg}"
        );
        assert!(dbg.contains("<redacted>"), "expected <redacted>: {dbg}");
        // token_type should still print so logs remain useful.
        assert!(dbg.contains("bearer"), "token_type should remain: {dbg}");
    }
}
