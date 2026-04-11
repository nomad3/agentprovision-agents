use tonic::{transport::Server, Request, Response, Status};
use tonic_health::server::health_reporter;
use embedding::v1::embedding_service_server::{EmbeddingService, EmbeddingServiceServer};
use embedding::v1::{EmbedRequest, EmbedResponse, EmbedBatchRequest, EmbedBatchResponse, HealthResponse};
use std::sync::Arc;
use std::time::{Duration, Instant};

use fastembed::{TextEmbedding, InitOptions, EmbeddingModel};
use tokio::sync::Mutex;

pub mod embedding {
    pub mod v1 {
        tonic::include_proto!("embedding.v1");
    }
}

/// Wraps fastembed::TextEmbedding (which uses ONNX Runtime internally).
/// fastembed handles model download, tokenization, ONNX inference, and
/// normalization — we just call embed() and get 768-dim vectors back.
pub struct MyEmbeddingService {
    model: Arc<Mutex<TextEmbedding>>,
    start_time: Instant,
}

impl MyEmbeddingService {
    pub fn new(model: TextEmbedding) -> Self {
        Self {
            model: Arc::new(Mutex::new(model)),
            start_time: Instant::now(),
        }
    }
}

#[tonic::async_trait]
impl EmbeddingService for MyEmbeddingService {
    async fn embed(&self, request: Request<EmbedRequest>) -> Result<Response<EmbedResponse>, Status> {
        let req = request.into_inner();
        let prefix = match req.task_type.as_str() {
            "search_query" => "search_query: ",
            "search_document" => "search_document: ",
            "classification" => "classification: ",
            "clustering" => "clustering: ",
            _ => "",
        };
        let text = format!("{}{}", prefix, req.text);

        let model = self.model.clone();
        let vector = tokio::task::spawn_blocking(move || {
            let m = model.blocking_lock();
            m.embed(vec![text], None)
        }).await
            .map_err(|e| Status::internal(format!("join error: {}", e)))?
            .map_err(|e| Status::internal(format!("embed error: {}", e)))?;

        let vec = vector.into_iter().next()
            .ok_or_else(|| Status::internal("no embedding returned"))?;

        Ok(Response::new(EmbedResponse {
            vector: vec,
            model: "nomic-embed-text-v1.5".to_string(),
            dimensions: 768,
        }))
    }

    async fn embed_batch(&self, request: Request<EmbedBatchRequest>) -> Result<Response<EmbedBatchResponse>, Status> {
        let req = request.into_inner();
        let task_type = req.task_type.clone();
        let prefix = match task_type.as_str() {
            "search_query" => "search_query: ",
            "search_document" => "search_document: ",
            "classification" => "classification: ",
            "clustering" => "clustering: ",
            _ => "",
        };

        let texts: Vec<String> = req.texts.iter()
            .map(|t| format!("{}{}", prefix, t))
            .collect();

        let model = self.model.clone();
        let vectors = tokio::task::spawn_blocking(move || {
            let m = model.blocking_lock();
            m.embed(texts, None)
        }).await
            .map_err(|e| Status::internal(format!("join error: {}", e)))?
            .map_err(|e| Status::internal(format!("batch embed error: {}", e)))?;

        let results = vectors.into_iter().map(|v| EmbedResponse {
            vector: v,
            model: "nomic-embed-text-v1.5".to_string(),
            dimensions: 768,
        }).collect();

        Ok(Response::new(EmbedBatchResponse { results }))
    }

    async fn health(&self, _request: Request<()>) -> Result<Response<HealthResponse>, Status> {
        Ok(Response::new(HealthResponse {
            status: "ok".to_string(),
            model: "nomic-embed-text-v1.5".to_string(),
            uptime_seconds: self.start_time.elapsed().as_secs() as i64,
        }))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();

    tracing::info!("Loading nomic-embed-text-v1.5 via fastembed (ONNX Runtime)...");
    let model = TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::NomicEmbedTextV15)
            .with_show_download_progress(true)
    )?;

    // Warmup
    tracing::info!("Warming up...");
    let test = model.embed(vec!["warmup"], None)?;
    tracing::info!("Warmup: {} dimensions", test[0].len());

    let service = MyEmbeddingService::new(model);

    let (mut health_reporter, health_service) = health_reporter();
    health_reporter
        .set_serving::<EmbeddingServiceServer<MyEmbeddingService>>()
        .await;

    let addr = "0.0.0.0:50051".parse()?;
    tracing::info!("EmbeddingService listening on {}", addr);

    Server::builder()
        .timeout(Duration::from_secs(30))
        .add_service(health_service)
        .add_service(EmbeddingServiceServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
