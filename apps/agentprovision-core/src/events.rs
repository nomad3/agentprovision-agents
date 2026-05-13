//! Session-event SSE consumer.
//!
//! Tail `/api/v1/chat/sessions/{id}/events/stream` to surface chat +
//! collaboration events live (workflow steps, blackboard entries, agent
//! status updates).
//!
//! Also exposes `tail_task_events` (#188) — same protocol against the
//! task-fanout SSE endpoint, used by `alpha watch` to replace the 1.5s
//! poll loop.

use eventsource_stream::Eventsource;
use futures_util::stream::Stream;
use futures_util::StreamExt;

use crate::client::ApiClient;
use crate::error::{Error, Result};

#[derive(Debug, Clone)]
pub struct SessionEvent {
    pub event: Option<String>,
    pub data: String,
}

pub async fn tail_session_events(
    client: &ApiClient,
    session_id: &str,
) -> Result<impl Stream<Item = Result<SessionEvent>>> {
    let url = client.build_url(&format!("/api/v1/chat/sessions/{session_id}/events/stream"))?;
    let mut req = client.http().get(url).header("Accept", "text/event-stream");
    if let Some(tok) = client.token() {
        req = req.header("Authorization", format!("Bearer {tok}"));
    }
    let resp = req.send().await?;
    if !resp.status().is_success() {
        let status = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        return Err(Error::Api { status, body });
    }
    let stream = resp.bytes_stream().eventsource().map(|res| {
        let ev = res.map_err(|e| Error::other(format!("sse error: {e}")))?;
        Ok(SessionEvent {
            event: if ev.event.is_empty() {
                None
            } else {
                Some(ev.event)
            },
            data: ev.data,
        })
    });
    Ok(stream)
}

// ─── #188: tail_task_events for `alpha watch` ────────────────────────────

/// One event in the task-fanout SSE stream. The `event` field is one of:
///   - "status"        — parent status change. data = {task_id, status}
///   - "child_status"  — fanout child status change. data = {task_id,
///                       provider, status}
///   - "result"        — terminal result body. data = {merged_text}
///   - "ended"         — stream finalized. data = {status}
///   - "timeout"       — server-side deadline hit. data = {detail}
///   - "error"         — server-side soft fail. data = {detail}
///
/// Caller is responsible for breaking the consumer loop on "ended" /
/// "timeout" / "error" — the SSE stream itself terminates naturally
/// after, but the events carry the semantic meaning the CLI renders.
#[derive(Debug, Clone)]
pub struct TaskEvent {
    pub event: Option<String>,
    pub data: String,
}

/// Tail `/api/v1/tasks-fanout/{task_id}/events/stream`. Pairs with
/// `alpha watch <task_id>` (#188) — replaces the 1.5s poll loop with
/// SSE so the client doesn't hammer /status. Server-side polls
/// Temporal (or the in-memory stub) and emits transitions only.
pub async fn tail_task_events(
    client: &ApiClient,
    task_id: &str,
) -> Result<impl Stream<Item = Result<TaskEvent>>> {
    let url = client.build_url(&format!("/api/v1/tasks-fanout/{task_id}/events/stream"))?;
    let mut req = client.http().get(url).header("Accept", "text/event-stream");
    if let Some(tok) = client.token() {
        req = req.header("Authorization", format!("Bearer {tok}"));
    }
    let resp = req.send().await?;
    if !resp.status().is_success() {
        let status = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        return Err(Error::Api { status, body });
    }
    let stream = resp.bytes_stream().eventsource().map(|res| {
        let ev = res.map_err(|e| Error::other(format!("sse error: {e}")))?;
        Ok(TaskEvent {
            event: if ev.event.is_empty() {
                None
            } else {
                Some(ev.event)
            },
            data: ev.data,
        })
    });
    Ok(stream)
}
