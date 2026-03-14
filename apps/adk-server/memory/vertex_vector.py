"""Embedding service using nomic-embed-text-v1.5 (local, no API key needed)."""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

_model = None
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIMS = 768


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
        logger.info(f"Loaded embedding model: {EMBEDDING_MODEL}")
    return _model


class EmbeddingService:
    """Generate embeddings via nomic-embed-text-v1.5 (local)."""

    async def get_embedding(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
        try:
            model = _get_model()
            truncated = text[:8000]

            # Nomic-embed uses task-specific prefixes
            if task_type == "RETRIEVAL_QUERY":
                prefixed = f"search_query: {truncated}"
            else:
                prefixed = f"search_document: {truncated}"

            embedding = model.encode(prefixed, normalize_embeddings=True)
            return embedding.tolist()
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return None

    async def get_embeddings_batch(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[Optional[List[float]]]:
        try:
            model = _get_model()
            prefix = "search_query: " if task_type == "RETRIEVAL_QUERY" else "search_document: "
            prefixed = [f"{prefix}{t[:8000]}" for t in texts]
            embeddings = model.encode(prefixed, normalize_embeddings=True, batch_size=32)
            return [e.tolist() for e in embeddings]
        except Exception as e:
            logger.error("Batch embedding failed: %s", e)
            return [None] * len(texts)


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
