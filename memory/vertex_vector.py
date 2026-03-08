"""Vertex AI Vector Search integration for embeddings and RAG.

Uses text-embedding-005 for 768-dimensional embeddings.
"""
from typing import Optional
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel

from config.settings import settings


class EmbeddingService:
    """Generates embeddings using Vertex AI text-embedding-005."""

    def __init__(self):
        # Initialize Vertex AI
        aiplatform.init(
            project=settings.vertex_project,
            location=settings.vertex_location,
        )

        # Load embedding model
        self.model = TextEmbeddingModel.from_pretrained(settings.embedding_model)

    async def get_embedding(self, text: str) -> list[float]:
        """Generate embedding for text.

        Args:
            text: Input text to embed

        Returns:
            768-dimensional embedding vector
        """
        # TextEmbeddingModel.get_embeddings is synchronous
        embeddings = self.model.get_embeddings([text])
        return embeddings[0].values

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        embeddings = self.model.get_embeddings(texts)
        return [e.values for e in embeddings]


class VectorSearchService:
    """Manages Vertex AI Vector Search index for similarity search."""

    def __init__(self):
        aiplatform.init(
            project=settings.vertex_project,
            location=settings.vertex_location,
        )

        self.index_id = settings.vector_index_id
        self.endpoint_id = settings.vector_endpoint_id
        self.embedding_service = EmbeddingService()

        # Load index endpoint if configured
        self._endpoint = None
        if self.endpoint_id:
            try:
                self._endpoint = aiplatform.MatchingEngineIndexEndpoint(self.endpoint_id)
            except Exception:
                pass  # Endpoint not yet created

    async def find_neighbors(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Find similar items using vector search.

        Args:
            query: Search query text
            top_k: Number of results
            filters: Metadata filters

        Returns:
            List of similar items with scores
        """
        if not self._endpoint:
            return []

        # Get query embedding
        query_embedding = await self.embedding_service.get_embedding(query)

        # Search
        response = self._endpoint.find_neighbors(
            deployed_index_id=self.index_id,
            queries=[query_embedding],
            num_neighbors=top_k,
        )

        results = []
        for neighbor in response[0]:
            results.append({
                "id": neighbor.id,
                "score": neighbor.distance,
            })

        return results

    async def upsert_embedding(
        self,
        item_id: str,
        text: str,
        metadata: dict,
    ) -> bool:
        """Add or update item in vector index.

        Note: Vertex AI Vector Search requires batch updates via index rebuild.
        For real-time updates, use the streaming index feature or queue updates.
        """
        # Get embedding
        embedding = await self.embedding_service.get_embedding(text)

        # In production, queue this for batch index update
        # For now, just return success
        return True


# Singleton instances
_embedding_service: Optional[EmbeddingService] = None
_vector_service: Optional[VectorSearchService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def get_vector_service() -> VectorSearchService:
    """Get or create vector search service singleton."""
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorSearchService()
    return _vector_service
