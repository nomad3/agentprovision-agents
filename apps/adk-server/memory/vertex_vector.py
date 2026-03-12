"""Embedding service using Gemini Embedding 2."""
import logging
from typing import List, Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_client = None
EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMS = 768


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


class EmbeddingService:
    """Generate embeddings via Gemini Embedding 2."""

    async def get_embedding(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
        if not settings.google_api_key:
            return None
        try:
            from google.genai import types
            client = _get_client()
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text[:8000],
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=EMBEDDING_DIMS,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return None

    async def get_embeddings_batch(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[Optional[List[float]]]:
        results = []
        for t in texts:
            results.append(await self.get_embedding(t, task_type))
        return results


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
