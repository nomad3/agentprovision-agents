//! Streaming chat helper.
//!
//! Hits `POST /api/v1/chat/sessions/{id}/messages/stream` and yields incremental
//! text deltas as they arrive. The backend emits Server-Sent Events with a
//! payload like `{"delta": "..."}` per chunk (and a final `{"done": true}`
//! event). We surface the deltas as a `Stream<Item = Result<ChatStreamEvent>>`.

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
    #[serde(default)]
    delta: Option<String>,
    #[serde(default)]
    text: Option<String>,
    #[serde(default)]
    done: Option<bool>,
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
                    if w.done.unwrap_or(false) {
                        return Ok(ChatStreamEvent::Done);
                    }
                    if let Some(d) = w.delta.or(w.text) {
                        return Ok(ChatStreamEvent::Delta(d));
                    }
                    Ok(ChatStreamEvent::Other(ev.data))
                }
                Err(_) => Ok(ChatStreamEvent::Other(ev.data)),
            }
        });
    Ok(stream)
}
