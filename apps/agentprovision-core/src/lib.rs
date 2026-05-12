//! AgentProvision Core
//!
//! Shared Rust business logic consumed by the Luna desktop client (Tauri) and
//! the `agentprovision` CLI. This crate is the single source of truth for:
//!
//! * API client construction (auth header, base URL, error model)
//! * Authentication (token storage in OS keychain, device-flow login,
//!   email/password login, refresh)
//! * API models (Tenant, Agent, Workflow, ChatMessage, etc.)
//! * Streaming chat helper (SSE consumer)
//! * Session-event SSE consumer (`/chat/sessions/{id}/events/stream`)
//! * MCP tool client
//! * `~/.config/agentprovision/config.toml` reader/writer
//!
//! The crate is GUI-/CLI-agnostic. It exposes async APIs that any front-end
//! can drive.

pub mod auth;
pub mod chat;
pub mod client;
pub mod config;
pub mod error;
pub mod events;
pub mod mcp;
pub mod models;
pub mod runtime;
pub mod training;

pub use client::ApiClient;
pub use error::{Error, Result};
pub use runtime::{
    mint_agent_token_for_runtime, preflight, preflight_all, MintedAgentToken, PreflightReport,
    RuntimeId,
};
