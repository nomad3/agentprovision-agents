//! Session-event SSE consumer.
//!
//! Tail `/api/v1/chat/sessions/{id}/events/stream` to surface chat +
//! collaboration events live (workflow steps, blackboard entries, agent
//! status updates).

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
