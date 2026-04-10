import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("EMBEDDING_SERVICE_URL"),
    reason="EMBEDDING_SERVICE_URL not set"
)


def test_embed_single():
    """Single text embedding returns 768-dim vector."""
    from app.generated import embedding_pb2, embedding_pb2_grpc
    import grpc
    channel = grpc.insecure_channel(os.environ["EMBEDDING_SERVICE_URL"])
    stub = embedding_pb2_grpc.EmbeddingServiceStub(channel)
    response = stub.Embed(embedding_pb2.EmbedRequest(text="hello world", task_type="search_query"))
    assert len(response.vector) == 768
    assert response.model == "nomic-embed-text-v1.5"


def test_embed_batch():
    """Batch embedding returns correct count of results."""
    from app.generated import embedding_pb2, embedding_pb2_grpc
    import grpc
    channel = grpc.insecure_channel(os.environ["EMBEDDING_SERVICE_URL"])
    stub = embedding_pb2_grpc.EmbeddingServiceStub(channel)
    response = stub.EmbedBatch(embedding_pb2.EmbedBatchRequest(
        texts=["hello", "world", "test"], task_type="search_document"
    ))
    assert len(response.results) == 3
    for r in response.results:
        assert len(r.vector) == 768
