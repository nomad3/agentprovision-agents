//! Minimal MCP-tool client.
//!
//! The CLI exposes `agentprovision tool call <tool> --arg KEY=VAL` for
//! power users; this module provides the underlying call. We hit the API's
//! internal MCP-proxy surface rather than the MCP server directly, so auth
//! stays uniform.

use serde::Serialize;

use crate::client::ApiClient;
use crate::error::Result;

#[derive(Debug, Clone, Serialize)]
struct McpCallRequest<'a> {
    tool: &'a str,
    args: serde_json::Value,
}

/// Call an MCP tool by name. Returns the raw JSON result.
///
/// `args` is an arbitrary JSON object. The CLI builds it from
/// `--arg KEY=VAL` flags.
pub async fn call_tool(
    client: &ApiClient,
    tool: &str,
    args: serde_json::Value,
) -> Result<serde_json::Value> {
    let req = client
        .request(reqwest::Method::POST, "/api/v1/mcp/call")?
        .json(&McpCallRequest { tool, args });
    client.send_json(req).await
}
