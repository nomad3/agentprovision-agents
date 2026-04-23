"""Unified LLM Service for multi-provider support."""
from typing import List, Dict, Any, Optional
import uuid

from sqlalchemy.orm import Session

from app.services.llm.router import LLMRouter
from app.services.llm.provider_factory import LLMProviderFactory


class LLMService:
    """Unified service for LLM interactions across multiple providers."""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.router = LLMRouter(db)
        self.factory = LLMProviderFactory()

    def generate_response(
        self,
        messages: List[Dict[str, str]],
        task_type: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs
    ) -> Any:
        """
        Generate a response using the optimal model for the task.

        Args:
            messages: List of messages in OpenAI format
            task_type: Type of task for routing (coding, creative, analysis, etc.)
            max_tokens: Maximum tokens in response
            temperature: Response creativity

        Returns:
            OpenAI-compatible response object
        """
        # 1. Get active config for the tenant
        config = self.router.get_active_config(self.tenant_id)
        
        provider = config["provider"]
        model_id = config["model_id"]
        api_key = config["api_key"]

        if not api_key:
            raise ValueError(f"No API key configured for provider: {provider}")

        # 2. Factory creates provider client
        client = self.factory.get_client(provider, api_key)

        # 3. Make request
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        # 4. Track usage
        self.router.track_usage(
            tenant_id=self.tenant_id,
            model_id=model_id,
            tokens_input=response.usage.prompt_tokens,
            tokens_output=response.usage.completion_tokens,
            cost=0.0 # We'll need a better way to get per-model cost if needed
        )

        return response
