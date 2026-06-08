//! PR-A A0 verify spike: does reqwest's CLIENT-LEVEL total `.timeout()` fire
//! while consuming a `bytes_stream()` (SSE) body?
//!
//! `ApiClient::new` builds the client with `.timeout(Duration::from_secs(180))`
//! (client.rs) and a comment claiming streaming endpoints "aren't bounded by
//! this timeout because they consume bytes_stream". This spike PROVES or refutes
//! that on the repo's pinned reqwest, using a production-style client with a
//! SHORT timeout so the test is fast/deterministic (the 180s value is irrelevant
//! to the behavioral question).
//!
//! Discovery test, not a happy-path gate: it CLASSIFIES the outcome and prints
//! the implied A1 decision. It panics only on an UNEXPECTED third outcome
//! (non-timeout transport error, or early clean close), so it cannot lie.
//!
//! Run: cargo test --test stream_timeout_spike -- --nocapture
//!
//! Mock server uses raw `tokio::net::TcpListener`, not wiremock, so the spike
//! exercises a real streamed HTTP response without external test machinery.

use std::time::{Duration, Instant};

use futures_util::StreamExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const CLIENT_TIMEOUT: Duration = Duration::from_secs(1); // stand-in for prod 180s
const SERVER_HOLD: Duration = Duration::from_secs(4); // > CLIENT_TIMEOUT, socket stays OPEN
const TEST_GUARD: Duration = Duration::from_secs(6); // hard cap so the test can't hang

enum Sig {
    Err {
        at: Duration,
        is_timeout: bool,
        msg: String,
    },
    Ended {
        at: Duration,
    },
}

async fn write_chunk(sock: &mut TcpStream, body: &str) -> std::io::Result<()> {
    // HTTP/1.1 chunked frame.
    let frame = format!("{:x}\r\n{}\r\n", body.len(), body);
    sock.write_all(frame.as_bytes()).await?;
    sock.flush().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reqwest_total_timeout_vs_bytes_stream() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    // Mock SSE server: headers + one frame immediately, then idle (socket OPEN)
    // past CLIENT_TIMEOUT, then a liveness frame. Never closes during the window,
    // so the only possible early error is the client's own timeout.
    let server = tokio::spawn(async move {
        let (mut sock, _) = listener.accept().await.unwrap();
        let mut buf = [0u8; 1024];
        let _ = sock.read(&mut buf).await; // drain request headers
        sock.write_all(
            b"HTTP/1.1 200 OK\r\n\
              Content-Type: text/event-stream\r\n\
              Cache-Control: no-cache\r\n\
              Transfer-Encoding: chunked\r\n\
              Connection: keep-alive\r\n\r\n",
        )
        .await
        .unwrap();
        sock.flush().await.unwrap();
        let _ = write_chunk(
            &mut sock,
            "data: {\"type\":\"chunk\",\"seq\":1,\"text\":\"hi\"}\n\n",
        )
        .await;
        tokio::time::sleep(SERVER_HOLD).await;
        // Liveness probe AFTER the timeout window: if the client is still reading,
        // the timeout did NOT bound the stream.
        let _ = write_chunk(
            &mut sock,
            "data: {\"type\":\"chunk\",\"seq\":2,\"text\":\"alive\"}\n\n",
        )
        .await;
        tokio::time::sleep(Duration::from_secs(1)).await;
    });

    // Client built EXACTLY like ApiClient::new (total .timeout()).
    let client = reqwest::Client::builder()
        .timeout(CLIENT_TIMEOUT)
        .build()
        .unwrap();

    let start = Instant::now();
    let resp = client
        .get(format!("http://{addr}/"))
        .header("Accept", "text/event-stream")
        .send()
        .await
        .expect("headers should arrive well within the timeout");
    assert!(resp.status().is_success());

    let mut stream = resp.bytes_stream();
    let mut first_at: Option<Duration> = None;
    let mut second_seen = false;
    let outcome = tokio::time::timeout(TEST_GUARD, async {
        while let Some(item) = stream.next().await {
            match item {
                Ok(bytes) => {
                    if first_at.is_none() {
                        first_at = Some(start.elapsed());
                    }
                    if String::from_utf8_lossy(&bytes).contains("\"seq\":2") {
                        second_seen = true;
                    }
                }
                Err(e) => {
                    return Sig::Err {
                        at: start.elapsed(),
                        is_timeout: e.is_timeout(),
                        msg: e.to_string(),
                    }
                }
            }
        }
        Sig::Ended {
            at: start.elapsed(),
        }
    })
    .await;

    match outcome {
        Ok(Sig::Err {
            at,
            is_timeout,
            msg,
        }) => {
            assert!(
                is_timeout,
                "expected a TIMEOUT error, got transport error: {msg}"
            );
            assert!(
                at < SERVER_HOLD,
                "timeout error at {at:?} should precede the server idle {SERVER_HOLD:?}"
            );
            println!(
                "== A0 OUTCOME: TIMEOUT BITES the bytes_stream (fired at {at:?}, ~CLIENT_TIMEOUT)."
            );
            println!("== A0 DECISION: A1 REQUIRED — dedicated no-total-timeout stream client for /jobs/{{id}}/events.");
        }
        Ok(Sig::Ended { at }) => {
            assert!(
                second_seen || at >= CLIENT_TIMEOUT,
                "stream must have lived past CLIENT_TIMEOUT to count as 'does not bite'"
            );
            println!(
                "== A0 OUTCOME: timeout does NOT bound bytes_stream (alive past {CLIENT_TIMEOUT:?}; post-idle frame seen={second_seen})."
            );
            println!(
                "== A0 DECISION: NO client swap — A1 reduces to optional read-idle detection only."
            );
        }
        Err(_) => {
            // TEST_GUARD elapsed with no error → stream lived well past CLIENT_TIMEOUT.
            assert!(
                second_seen,
                "guard elapsed but the liveness frame was never observed"
            );
            println!("== A0 OUTCOME: timeout does NOT bound bytes_stream (guard elapsed; liveness frame seen).");
            println!(
                "== A0 DECISION: NO client swap — A1 reduces to optional read-idle detection only."
            );
        }
    }

    let _ = server.await;
}
