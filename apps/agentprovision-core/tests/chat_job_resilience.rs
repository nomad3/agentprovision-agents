//! PR-A2: idle-stall deadline + reconnect/truncated plumbing for the chat-job
//! event stream, exercised end-to-end through `ApiClient` + a `std::net` mock
//! SSE server (no wiremock; same pattern as `tests/stream_client_timeout.rs`).
//!
//! Each test spawns its own one-shot server on an ephemeral port and drives the
//! real `stream_chat_job_events` + `next_event_before` core path.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::time::Duration;

use agentprovision_core::chat::{
    next_event_before, stream_chat_job_events, ChatJobStreamEvent, NextEvent,
};
use agentprovision_core::client::ApiClient;
use agentprovision_core::error::ErrorKind;

const GUARD: Duration = Duration::from_secs(6); // hard cap so a hang can't wedge CI

fn write_chunk(sock: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let frame = format!("{:x}\r\n{}\r\n", body.len(), body); // HTTP/1.1 chunked
    sock.write_all(frame.as_bytes())?;
    sock.flush()
}

fn send_headers(sock: &mut TcpStream) {
    let _ = sock.write_all(
        b"HTTP/1.1 200 OK\r\n\
          Content-Type: text/event-stream\r\n\
          Cache-Control: no-cache\r\n\
          Transfer-Encoding: chunked\r\n\
          Connection: keep-alive\r\n\r\n",
    );
    let _ = sock.flush();
}

/// Accept one connection, drain the request headers, then hand the socket to
/// `serve`. Returns the bound address.
fn spawn_server<F>(serve: F) -> SocketAddr
where
    F: FnOnce(&mut TcpStream) + Send + 'static,
{
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    std::thread::spawn(move || {
        if let Ok((mut sock, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = sock.read(&mut buf); // drain request headers; content ignored
            serve(&mut sock);
        }
    });
    addr
}

fn client_for(addr: SocketAddr) -> ApiClient {
    ApiClient::new(&format!("http://{addr}")).expect("client builds")
}

const CHUNK_SEQ1: &str =
    "data: {\"type\":\"event\",\"seq\":1,\"kind\":\"chunk\",\"payload\":{\"text\":\"hi\"}}\n\n";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn yields_chunk_then_stalls_when_idle_past_deadline() {
    // chunk seq:1, then idle with the socket OPEN. The idle-stall primitive
    // returns the chunk, then Stalled once the short deadline elapses.
    let addr = spawn_server(|sock| {
        send_headers(sock);
        let _ = write_chunk(sock, CHUNK_SEQ1);
        std::thread::sleep(Duration::from_secs(3)); // idle, socket open
    });
    let client = client_for(addr);
    let mut stream = stream_chat_job_events(&client, "job1", 0)
        .await
        .expect("stream opens");

    let first = tokio::time::timeout(
        GUARD,
        next_event_before(
            &mut stream,
            tokio::time::Instant::now() + Duration::from_secs(2),
        ),
    )
    .await
    .expect("guard not hit")
    .expect("no transport error");
    match first {
        NextEvent::Event(ChatJobStreamEvent::Chunk { seq, text }) => {
            assert_eq!(seq, 1);
            assert_eq!(text, "hi");
        }
        other => panic!("expected chunk, got {other:?}"),
    }

    let second = tokio::time::timeout(
        GUARD,
        next_event_before(
            &mut stream,
            tokio::time::Instant::now() + Duration::from_millis(300),
        ),
    )
    .await
    .expect("guard not hit")
    .expect("no transport error");
    assert!(matches!(second, NextEvent::Stalled), "got {second:?}");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reconnect_signal_via_timeout_frame() {
    // chunk seq:1 then a cooperative timeout frame: both surface as events so
    // the caller can advance its cursor and reconnect by seq.
    let addr = spawn_server(|sock| {
        send_headers(sock);
        let _ = write_chunk(sock, CHUNK_SEQ1);
        let _ = write_chunk(sock, "data: {\"type\":\"timeout\",\"last_seq\":1}\n\n");
        std::thread::sleep(Duration::from_millis(200));
    });
    let client = client_for(addr);
    let mut stream = stream_chat_job_events(&client, "job1", 0)
        .await
        .expect("stream opens");
    let deadline = tokio::time::Instant::now() + Duration::from_secs(2);

    let a = next_event_before(&mut stream, deadline).await.expect("ok");
    assert!(
        matches!(
            a,
            NextEvent::Event(ChatJobStreamEvent::Chunk { seq: 1, .. })
        ),
        "got {a:?}"
    );

    let b = next_event_before(&mut stream, deadline).await.expect("ok");
    assert!(
        matches!(
            b,
            NextEvent::Event(ChatJobStreamEvent::Timeout { last_seq: 1 })
        ),
        "got {b:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn truncated_frame_surfaces_gap() {
    let addr = spawn_server(|sock| {
        send_headers(sock);
        let _ = write_chunk(sock, "data: {\"type\":\"truncated\",\"from_seq\":5}\n\n");
        std::thread::sleep(Duration::from_millis(200));
    });
    let client = client_for(addr);
    let mut stream = stream_chat_job_events(&client, "job1", 0)
        .await
        .expect("stream opens");
    let ev = next_event_before(
        &mut stream,
        tokio::time::Instant::now() + Duration::from_secs(2),
    )
    .await
    .expect("ok");
    assert!(
        matches!(
            ev,
            NextEvent::Event(ChatJobStreamEvent::Truncated { from_seq: 5 })
        ),
        "got {ev:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn clean_close_yields_ended() {
    let addr = spawn_server(|sock| {
        send_headers(sock);
        // End the chunked body, then drop the socket (closure returns) to close.
        let _ = sock.write_all(b"0\r\n\r\n");
        let _ = sock.flush();
    });
    let client = client_for(addr);
    let mut stream = stream_chat_job_events(&client, "job1", 0)
        .await
        .expect("stream opens");

    let ended = tokio::time::timeout(GUARD, async {
        loop {
            match next_event_before(
                &mut stream,
                tokio::time::Instant::now() + Duration::from_secs(2),
            )
            .await
            {
                Ok(NextEvent::Ended) => return true,
                Ok(NextEvent::Event(_)) => continue, // drain any stray frame
                Ok(NextEvent::Stalled) => return false,
                Err(_) => return false,
            }
        }
    })
    .await
    .expect("guard not hit");
    assert!(ended, "expected Ended on clean close");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abrupt_mid_stream_drop_is_retryable_transport_error() {
    // One complete chunk, then a chunk header promising more bytes than are
    // sent, then an abrupt socket drop: an incomplete chunked body that reqwest
    // surfaces as a transport/body error (the proxy-RST-mid-SSE case). It must
    // classify as retryable so the CLI reconnects by seq rather than bailing.
    let addr = spawn_server(|sock| {
        send_headers(sock);
        let _ = write_chunk(sock, CHUNK_SEQ1);
        // 0x40 = promise 64 bytes, send far fewer, then drop (no terminator).
        let _ = sock.write_all(b"40\r\ndata: {\"type\":\"event\",\"seq\":2");
        let _ = sock.flush();
        // closure returns -> socket dropped mid-frame.
    });
    let client = client_for(addr);
    let mut stream = stream_chat_job_events(&client, "job1", 0)
        .await
        .expect("stream opens");

    let retryable = tokio::time::timeout(GUARD, async {
        loop {
            match next_event_before(
                &mut stream,
                tokio::time::Instant::now() + Duration::from_secs(3),
            )
            .await
            {
                Ok(NextEvent::Event(_)) => continue, // drain the first complete chunk
                Ok(NextEvent::Ended) => return None, // graceful close: not the case under test
                Ok(NextEvent::Stalled) => return None,
                Err(e) => return Some((e.kind(), e.is_retryable())),
            }
        }
    })
    .await
    .expect("guard not hit");

    assert_eq!(
        retryable,
        Some((ErrorKind::Transport, true)),
        "an abrupt mid-stream drop must be a retryable transport error so the CLI reconnects by seq"
    );
}
