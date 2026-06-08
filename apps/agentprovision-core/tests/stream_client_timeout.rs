//! PR-A1 regression: the dedicated stream client (`build_stream_client`) has NO
//! total timeout, so a long-idle SSE body survives past where the unary 180s
//! total-timeout client would have cut it. Contrast test proves a total-timeout
//! client DOES cut the same body, so the regression is meaningful.
//!
//! Non-flaky: a std::net mock SSE server (own OS thread) sends headers + a frame,
//! idles past a short window with the socket OPEN, then sends a late frame.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::time::{Duration, Instant};

use agentprovision_core::client::build_stream_client;
use futures_util::StreamExt;

const SHORT_TIMEOUT: Duration = Duration::from_secs(1);
const SERVER_IDLE: Duration = Duration::from_secs(2); // > SHORT_TIMEOUT
const GUARD: Duration = Duration::from_secs(6); // hard cap so a hang can't wedge CI

fn write_chunk(sock: &mut TcpStream, body: &str) -> std::io::Result<()> {
    let frame = format!("{:x}\r\n{}\r\n", body.len(), body); // HTTP/1.1 chunked
    sock.write_all(frame.as_bytes())?;
    sock.flush()
}

/// Accept one connection, send headers + seq:1, idle (socket OPEN) past
/// SERVER_IDLE, then send seq:2. Never closes during the window, so the only
/// possible early stream error is the client's own total timeout.
fn spawn_idle_sse_server() -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    std::thread::spawn(move || {
        if let Ok((mut sock, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = sock.read(&mut buf); // drain request headers
            let _ = sock.write_all(
                b"HTTP/1.1 200 OK\r\n\
                  Content-Type: text/event-stream\r\n\
                  Cache-Control: no-cache\r\n\
                  Transfer-Encoding: chunked\r\n\
                  Connection: keep-alive\r\n\r\n",
            );
            let _ = sock.flush();
            let _ = write_chunk(&mut sock, "data: {\"type\":\"chunk\",\"seq\":1}\n\n");
            std::thread::sleep(SERVER_IDLE);
            let _ = write_chunk(&mut sock, "data: {\"type\":\"chunk\",\"seq\":2}\n\n");
            std::thread::sleep(Duration::from_secs(1));
        }
    });
    addr
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stream_client_survives_past_total_timeout_window() {
    let addr = spawn_idle_sse_server();
    let client = build_stream_client().expect("stream client builds");
    let resp = client
        .get(format!("http://{addr}/"))
        .header("Accept", "text/event-stream")
        .send()
        .await
        .expect("headers arrive");
    assert!(resp.status().is_success());

    let mut stream = resp.bytes_stream();
    let mut got_late_frame = false;
    let _ = tokio::time::timeout(GUARD, async {
        while let Some(item) = stream.next().await {
            match item {
                Ok(bytes) => {
                    if String::from_utf8_lossy(&bytes).contains("\"seq\":2") {
                        got_late_frame = true;
                        break;
                    }
                }
                Err(e) => panic!(
                    "stream client must NOT error on a long-idle stream (is_timeout={}): {e}",
                    e.is_timeout()
                ),
            }
        }
    })
    .await;

    assert!(
        got_late_frame,
        "stream client should receive the post-idle frame - no total timeout bounds it"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn total_timeout_client_cuts_the_same_body() {
    // Contrast: a client WITH a total timeout dies before the late frame - this
    // is exactly the failure build_stream_client avoids.
    let addr = spawn_idle_sse_server();
    let client = reqwest::Client::builder()
        .timeout(SHORT_TIMEOUT)
        .user_agent("a1-regression")
        .build()
        .unwrap();
    let resp = client.get(format!("http://{addr}/")).send().await.unwrap();
    assert!(resp.status().is_success());

    let mut stream = resp.bytes_stream();
    let start = Instant::now();
    let mut timed_out = false;
    let _ = tokio::time::timeout(GUARD, async {
        while let Some(item) = stream.next().await {
            if let Err(e) = item {
                timed_out = e.is_timeout();
                break;
            }
        }
    })
    .await;

    assert!(
        timed_out,
        "total-timeout client should time out on the idle stream"
    );
    assert!(
        start.elapsed() < SERVER_IDLE,
        "should cut before the {SERVER_IDLE:?} idle ends, got {:?}",
        start.elapsed()
    );
}
