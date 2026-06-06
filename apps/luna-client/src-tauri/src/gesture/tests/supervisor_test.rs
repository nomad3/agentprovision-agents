use crate::gesture::{engine_status, pause_engine, stop_engine};

#[tokio::test]
async fn stop_engine_clears_paused_status() {
    pause_engine()
        .await
        .expect("pause should not require an app handle");
    assert_eq!(engine_status().await.state, "paused");

    stop_engine().await.expect("stop should clear paused state");
    assert_eq!(engine_status().await.state, "stopped");
}
