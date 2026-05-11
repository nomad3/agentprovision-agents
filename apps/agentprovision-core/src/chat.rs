//! Streaming chat helper.
//!
//! Hits `POST /api/v1/chat/sessions/{id}/messages/stream` and yields incremental
//! text deltas as they arrive.
//!
//! Wire format (current backend in `apps/api/app/api/v1/chat.py`):
//!   data: {"type":"user_saved","message":...}
//!   data: {"type":"token","text":"hello"}
//!   data: {"type":"token","text":" world"}
//!   data: {"type":"done","message":...}
//!   data: {"type":"error","detail":"..."}
//!
//! For backward / forward compatibility we also accept
//! `{"delta":"..."}` / `{"text":"..."}` / `{"done":true}` shapes and
//! the `[DONE]` sentinel some servers emit.

use eventsource_stream::Eventsource;
use futures_util::stream::Stream;
use futures_util::StreamExt;
use serde::Deserialize;

use crate::client::ApiClient;
use crate::error::{Error, Result};
use crate::models::ChatMessageRequest;

#[derive(Debug, Clone)]
pub enum ChatStreamEvent {
    /// Incremental text delta.
    Delta(String),
    /// Stream finished (final event).
    Done,
    /// An informational event we didn't recognise; surfaced raw for debug.
    Other(String),
}

#[derive(Debug, Deserialize)]
struct WireEvent {
    /// Discriminator on the new shape: "token" | "done" | "error" | "user_saved" | …
    #[serde(default, rename = "type")]
    event_type: Option<String>,
    /// Token text in the new shape.
    #[serde(default)]
    text: Option<String>,
    /// Legacy / OpenAI-style delta key.
    #[serde(default)]
    delta: Option<String>,
    /// Legacy boolean done sentinel.
    #[serde(default)]
    done: Option<bool>,
    /// Backend error detail when `type == "error"`.
    #[serde(default)]
    detail: Option<String>,
}

/// Open a streaming chat connection. Caller awaits the returned future to get
/// a `Stream` of `ChatStreamEvent`s.
pub async fn stream_chat(
    client: &ApiClient,
    session_id: &str,
    content: &str,
) -> Result<impl Stream<Item = Result<ChatStreamEvent>>> {
    let url = client.build_url(&format!(
        "/api/v1/chat/sessions/{session_id}/messages/stream"
    ))?;
    let mut req = client
        .http()
        .post(url)
        .header("Accept", "text/event-stream")
        .json(&ChatMessageRequest { content });
    if let Some(tok) = client.token() {
        req = req.header("Authorization", format!("Bearer {tok}"));
    }
    let resp = req.send().await?;
    if !resp.status().is_success() {
        let status = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        return Err(Error::Api { status, body });
    }
    let stream = resp
        .bytes_stream()
        .eventsource()
        .map(|res| -> Result<ChatStreamEvent> {
            let ev = res.map_err(|e| Error::other(format!("sse error: {e}")))?;
            if ev.data.is_empty() {
                return Ok(ChatStreamEvent::Other(String::new()));
            }
            // Some servers emit `[DONE]` as a sentinel.
            if ev.data.trim() == "[DONE]" {
                return Ok(ChatStreamEvent::Done);
            }
            let parsed: serde_json::Result<WireEvent> = serde_json::from_str(&ev.data);
            match parsed {
                Ok(w) => {
                    // Surface backend errors instead of silently dropping
                    // them (the previous behaviour left the user staring
                    // at a hung spinner).
                    if w.event_type.as_deref() == Some("error") {
                        let detail = w.detail.unwrap_or_else(|| ev.data.clone());
                        return Err(Error::other(format!("backend error: {detail}")));
                    }
                    // New shape: explicit `type: done` finalises the stream.
                    if w.event_type.as_deref() == Some("done") || w.done.unwrap_or(false) {
                        return Ok(ChatStreamEvent::Done);
                    }
                    // New shape: `type: token` carries the incremental text
                    // in `text`. We also accept the legacy `delta` key and
                    // a bare `text` field for any future renames.
                    let is_token = w.event_type.as_deref() == Some("token");
                    if is_token {
                        if let Some(t) = w.text {
                            return Ok(ChatStreamEvent::Delta(t));
                        }
                    }
                    if let Some(d) = w.delta {
                        return Ok(ChatStreamEvent::Delta(d));
                    }
                    if w.event_type.is_none() {
                        if let Some(t) = w.text {
                            return Ok(ChatStreamEvent::Delta(t));
                        }
                    }
                    // user_saved + future event types end up here.
                    Ok(ChatStreamEvent::Other(ev.data))
                }
                Err(_) => Ok(ChatStreamEvent::Other(ev.data)),
            }
        });
    Ok(stream)
}

// ──────────────────────────────────────────────────────────────────────
// Wire-format parser tests
// ──────────────────────────────────────────────────────────────────────
//
// The streaming endpoint is the most fragile part of the CLI <-> API
// contract, so the SSE-frame -> ChatStreamEvent translation gets dedicated
// coverage. Live integration tests live in apps/agentprovision-cli/tests.

#[cfg(test)]
mod tests {
    use super::*;

    /// Reproduce the parser block from `stream_chat` against a single SSE
    /// frame body so we can unit-test the contract without spinning up a
    /// real network stream.
    fn classify(frame: &str) -> Result<ChatStreamEvent> {
        if frame.is_empty() {
            return Ok(ChatStreamEvent::Other(String::new()));
        }
        if frame.trim() == "[DONE]" {
            return Ok(ChatStreamEvent::Done);
        }
        let parsed: serde_json::Result<WireEvent> = serde_json::from_str(frame);
        match parsed {
            Ok(w) => {
                if w.event_type.as_deref() == Some("error") {
                    let detail = w.detail.unwrap_or_else(|| frame.to_string());
                    return Err(Error::other(format!("backend error: {detail}")));
                }
                if w.event_type.as_deref() == Some("done") || w.done.unwrap_or(false) {
                    return Ok(ChatStreamEvent::Done);
                }
                let is_token = w.event_type.as_deref() == Some("token");
                if is_token {
                    if let Some(t) = w.text {
                        return Ok(ChatStreamEvent::Delta(t));
                    }
                }
                if let Some(d) = w.delta {
                    return Ok(ChatStreamEvent::Delta(d));
                }
                if w.event_type.is_none() {
                    if let Some(t) = w.text {
                        return Ok(ChatStreamEvent::Delta(t));
                    }
                }
                Ok(ChatStreamEvent::Other(frame.to_string()))
            }
            Err(_) => Ok(ChatStreamEvent::Other(frame.to_string())),
        }
    }

    fn unwrap_delta(ev: ChatStreamEvent) -> String {
        match ev {
            ChatStreamEvent::Delta(d) => d,
            other => panic!("expected Delta, got {other:?}"),
        }
    }

    #[test]
    fn parses_current_backend_token_shape() {
        let ev = classify(r#"{"type":"token","text":"hello"}"#).unwrap();
        assert_eq!(unwrap_delta(ev), "hello");
    }

    #[test]
    fn parses_current_backend_done_shape() {
        let ev = classify(r#"{"type":"done","message":{"id":"x"}}"#).unwrap();
        assert!(matches!(ev, ChatStreamEvent::Done));
    }

    #[test]
    fn parses_legacy_done_boolean() {
        let ev = classify(r#"{"done":true}"#).unwrap();
        assert!(matches!(ev, ChatStreamEvent::Done));
    }

    #[test]
    fn parses_legacy_delta_shape() {
        let ev = classify(r#"{"delta":"hi"}"#).unwrap();
        assert_eq!(unwrap_delta(ev), "hi");
    }

    #[test]
    fn parses_done_sentinel() {
        let ev = classify("[DONE]").unwrap();
        assert!(matches!(ev, ChatStreamEvent::Done));
    }

    #[test]
    fn surfaces_backend_errors_instead_of_dropping_them() {
        let err = classify(r#"{"type":"error","detail":"agent timed out"}"#).unwrap_err();
        let msg = format!("{err}");
        assert!(msg.contains("agent timed out"), "got: {msg}");
    }

    #[test]
    fn unknown_event_type_falls_through_to_other() {
        let ev = classify(r#"{"type":"user_saved","message":{"id":"x"}}"#).unwrap();
        assert!(matches!(ev, ChatStreamEvent::Other(_)));
    }

    #[test]
    fn malformed_json_falls_through_to_other() {
        let ev = classify("not json").unwrap();
        assert!(matches!(ev, ChatStreamEvent::Other(_)));
    }

    #[test]
    fn token_frame_without_text_is_other_not_panic() {
        let ev = classify(r#"{"type":"token"}"#).unwrap();
        assert!(matches!(ev, ChatStreamEvent::Other(_)));
    }
}
