//! PR-A2 item 3: reqwest errors classify into typed, retryable transport
//! variants. Connection-refused is deterministic (bind a port, then drop it so
//! it is closed) and must map to `Error::Offline`, which is retryable.

use std::net::TcpListener;

use agentprovision_core::client::build_stream_client;
use agentprovision_core::error::{Error, ErrorKind};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn connection_refused_maps_to_retryable_offline() {
    // Bind to grab a free port, then drop the listener so the port is closed.
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);

    let client = build_stream_client().expect("client builds");
    let reqwest_err = client
        .get(format!("http://{addr}/"))
        .send()
        .await
        .expect_err("connecting to a closed port must fail");

    // is_connect() should hold for connection-refused.
    assert!(
        reqwest_err.is_connect(),
        "expected a connect error, got: {reqwest_err}"
    );

    let err: Error = reqwest_err.into();
    assert!(
        matches!(err, Error::Offline(_)),
        "expected Offline, got {err:?}"
    );
    assert_eq!(err.kind(), ErrorKind::Offline);
    assert!(err.is_retryable(), "offline must be retryable");
}
