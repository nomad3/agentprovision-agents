//! Streaming chat helpers.
//!
//! Hits `POST /api/v1/chat/sessions/{id}/messages/stream` and yields incremental
//! text deltas as they arrive.
//!
//! Newer CLI surfaces should prefer the durable async-job flow:
//! `POST /messages/start` then `GET /chat/jobs/{id}/events?from_seq=N`.
//! That keeps each request short or heartbeat-backed, which avoids
//! Cloudflare 524s for long agent turns while preserving resumability.
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
use crate::models::{ChatJobEventPayload, ChatMessageRequest};

#[derive(Debug, Clone)]
pub enum ChatStreamEvent {
    /// Incremental text delta.
    Delta(String),
    /// Stream finished (final event).
    Done,
    /// An informational event we didn't recognise; surfaced raw for debug.
    Other(String),
}

#[derive(Debug, Clone)]
pub enum ChatJobStreamEvent {
    /// A reply text chunk from a `chat_job_events.kind == "chunk"` row.
    Chunk { seq: u64, text: String },
    /// A non-chunk event such as lifecycle/tool metadata.
    Event(ChatJobEventPayload),
    /// The job reached a terminal state.
    Terminal {
        status: String,
        result_message_id: Option<String>,
        error: Option<String>,
        last_seq: u64,
    },
    /// The server's SSE tail hit its reconnect ceiling; caller should reconnect.
    Timeout { last_seq: u64 },
    /// The server indicates the first replay batch was truncated.
    Truncated { from_seq: u64 },
    /// An informational frame we do not recognise.
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

#[derive(Debug, Deserialize)]
struct JobWireEvent {
    #[serde(default, rename = "type")]
    event_type: Option<String>,
    #[serde(default)]
    seq: Option<u64>,
    #[serde(default)]
    kind: Option<String>,
    #[serde(default)]
    payload: serde_json::Value,
    #[serde(default)]
    status: Option<String>,
    #[serde(default)]
    result_message_id: Option<String>,
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    last_seq: Option<u64>,
    #[serde(default)]
    from_seq: Option<u64>,
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

/// Open the reconnect-safe async chat-job SSE stream.
///
/// The server replays events with `seq > from_seq`, heartbeats while idle,
/// and emits a terminal frame before closing. If it emits a timeout frame,
/// callers should reconnect with the last sequence they rendered.
pub async fn stream_chat_job_events(
    client: &ApiClient,
    job_id: &str,
    from_seq: u64,
) -> Result<impl Stream<Item = Result<ChatJobStreamEvent>>> {
    let path = format!("/api/v1/chat/jobs/{job_id}/events");
    // Use the dedicated no-total-timeout stream client: the unary 180s timeout
    // bounds a bytes_stream body (A0, tests/stream_timeout_spike.rs), which would
    // kill a long agent turn's event stream mid-flight. PR-A1.
    let req = client
        .stream_request(reqwest::Method::GET, &path)?
        .header("Accept", "text/event-stream")
        .query(&[("from_seq", from_seq.to_string())]);
    let resp = req.send().await?;
    if !resp.status().is_success() {
        let status = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        return Err(Error::Api { status, body });
    }
    let stream = resp.bytes_stream().eventsource().map(|res| {
        let ev = res.map_err(|e| Error::other(format!("sse error: {e}")))?;
        parse_chat_job_event(&ev.data)
    });
    Ok(stream)
}

fn parse_chat_job_event(data: &str) -> Result<ChatJobStreamEvent> {
    if data.is_empty() {
        return Ok(ChatJobStreamEvent::Other(String::new()));
    }
    let parsed: serde_json::Result<JobWireEvent> = serde_json::from_str(data);
    let w = match parsed {
        Ok(w) => w,
        Err(_) => return Ok(ChatJobStreamEvent::Other(data.to_string())),
    };

    match w.event_type.as_deref() {
        Some("event") => {
            let seq = w.seq.unwrap_or(0);
            let kind = w.kind.unwrap_or_else(|| "unknown".to_string());
            if kind == "chunk" {
                let text = w
                    .payload
                    .get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string();
                return Ok(ChatJobStreamEvent::Chunk { seq, text });
            }
            Ok(ChatJobStreamEvent::Event(ChatJobEventPayload {
                seq,
                kind,
                payload: w.payload,
            }))
        }
        Some("terminal") => Ok(ChatJobStreamEvent::Terminal {
            status: w.status.unwrap_or_else(|| "unknown".to_string()),
            result_message_id: w.result_message_id,
            error: w.error,
            last_seq: w.last_seq.unwrap_or(0),
        }),
        Some("timeout") => Ok(ChatJobStreamEvent::Timeout {
            last_seq: w.last_seq.unwrap_or(0),
        }),
        Some("truncated") => Ok(ChatJobStreamEvent::Truncated {
            from_seq: w.from_seq.unwrap_or(0),
        }),
        Some("error") => {
            Err(Error::other(w.error.unwrap_or_else(|| {
                "chat job event stream reported an error".to_string()
            })))
        }
        _ => Ok(ChatJobStreamEvent::Other(data.to_string())),
    }
}

/// Outcome of awaiting the next chat-job event under an idle deadline.
///
/// Used by the CLI reconnect loop to implement an idle-stall deadline
/// (PR-A2 item 5): the caller resets `deadline` on each seq-advancing event,
/// so a returned [`NextEvent::Stalled`] means no progress arrived within the
/// idle window; the job is wedged, but the `job_id` is still resumable.
#[derive(Debug)]
pub enum NextEvent {
    /// A frame arrived before the deadline.
    Event(ChatJobStreamEvent),
    /// The deadline elapsed before any frame arrived (idle stall).
    Stalled,
    /// The stream closed cleanly with no further frames.
    Ended,
}

/// Await the next event from a chat-job stream, bounded by an absolute idle
/// `deadline`. Returns [`NextEvent::Stalled`] if the deadline passes with no
/// frame, [`NextEvent::Ended`] on clean close, [`NextEvent::Event`] otherwise.
/// Transport errors surface as `Err` so the caller can classify and reconnect.
///
/// The caller owns "idle since last seq": it recomputes `deadline` from the
/// last progress instant on every seq-advancing event, so heartbeats / unknown
/// frames (which do not advance `seq`) do not extend the deadline.
pub async fn next_event_before<S>(
    stream: &mut S,
    deadline: tokio::time::Instant,
) -> Result<NextEvent>
where
    S: Stream<Item = Result<ChatJobStreamEvent>> + Unpin,
{
    match tokio::time::timeout_at(deadline, stream.next()).await {
        Err(_elapsed) => Ok(NextEvent::Stalled),
        Ok(None) => Ok(NextEvent::Ended),
        Ok(Some(Ok(ev))) => Ok(NextEvent::Event(ev)),
        Ok(Some(Err(e))) => Err(e),
    }
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

    fn classify_job(frame: &str) -> Result<ChatJobStreamEvent> {
        parse_chat_job_event(frame)
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

    #[test]
    fn parses_chat_job_chunk_event() {
        let ev =
            classify_job(r#"{"type":"event","seq":7,"kind":"chunk","payload":{"text":"hello"}}"#)
                .unwrap();
        match ev {
            ChatJobStreamEvent::Chunk { seq, text } => {
                assert_eq!(seq, 7);
                assert_eq!(text, "hello");
            }
            other => panic!("expected chunk, got {other:?}"),
        }
    }

    #[test]
    fn parses_chat_job_lifecycle_event() {
        let ev = classify_job(
            r#"{"type":"event","seq":2,"kind":"lifecycle","payload":{"event":"started"}}"#,
        )
        .unwrap();
        match ev {
            ChatJobStreamEvent::Event(e) => {
                assert_eq!(e.seq, 2);
                assert_eq!(e.kind, "lifecycle");
                assert_eq!(e.payload["event"], "started");
            }
            other => panic!("expected lifecycle event, got {other:?}"),
        }
    }

    #[test]
    fn parses_chat_job_terminal_event() {
        let ev = classify_job(
            r#"{"type":"terminal","status":"done","result_message_id":"abc","last_seq":9}"#,
        )
        .unwrap();
        match ev {
            ChatJobStreamEvent::Terminal {
                status,
                result_message_id,
                last_seq,
                ..
            } => {
                assert_eq!(status, "done");
                assert_eq!(result_message_id.as_deref(), Some("abc"));
                assert_eq!(last_seq, 9);
            }
            other => panic!("expected terminal, got {other:?}"),
        }
    }

    #[test]
    fn parses_chat_job_timeout_event() {
        let ev = classify_job(r#"{"type":"timeout","last_seq":12}"#).unwrap();
        assert!(matches!(ev, ChatJobStreamEvent::Timeout { last_seq: 12 }));
    }
}
