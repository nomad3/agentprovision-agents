"""LLM Router for smart model selection using the Integration system."""
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import uuid
import logging

from app.models.tenant_features import TenantFeatures
from app.models.integration_config import IntegrationConfig
from app.services.orchestration.credential_vault import retrieve_credentials_for_skill

logger = logging.getLogger(__name__)

class LLMRouter:
    """Routes requests to optimal LLM based on active tenant integration."""

    def __init__(self, db: Session):
        self.db = db

    def get_active_provider(self, tenant_id: uuid.UUID) -> str:
        """Get the active LLM provider name for the tenant."""
        features = self.db.query(TenantFeatures).filter(
            TenantFeatures.tenant_id == tenant_id
        ).first()
        
        if features and features.active_llm_provider:
            return features.active_llm_provider
            
        return "gemini_llm" # Default

    def get_active_config(self, tenant_id: uuid.UUID) -> Dict[str, Any]:
        """
        Get the active LLM configuration (model and credentials) for a tenant.
        
        Returns a dict with 'provider', 'model_id', and 'api_key'.
        """
        provider = self.get_active_provider(tenant_id)
        
        # Look up IntegrationConfig
        config = self.db.query(IntegrationConfig).filter(
            IntegrationConfig.tenant_id == tenant_id,
            IntegrationConfig.integration_name == provider,
            IntegrationConfig.enabled.is_(True)
        ).first()
        
        if not config:
            logger.warning("No enabled IntegrationConfig found for provider %s on tenant %s", provider, tenant_id)
            return {"provider": provider, "model_id": "default", "api_key": None}

        # Get credentials from vault
        creds = retrieve_credentials_for_skill(self.db, config.id, tenant_id)
        
        return {
            "provider": provider.replace("_llm", ""),
            "model_id": creds.get("model", "default"),
            "api_key": creds.get("api_key")
        }

    def track_usage(
        self,
        tenant_id: uuid.UUID,
        model_id: str,
        tokens_input: int,
        tokens_output: int,
        cost: float = 0.0,
    ) -> None:
        """Track LLM usage for analytics."""
        from app.models.tenant_analytics import TenantAnalytics
        from datetime import datetime

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Update or create daily analytics
        analytics = self.db.query(TenantAnalytics).filter(
            TenantAnalytics.tenant_id == tenant_id,
            TenantAnalytics.period == "daily",
            TenantAnalytics.period_start == today,
        ).first()

        if analytics:
            analytics.total_tokens_used = (analytics.total_tokens_used or 0) + tokens_input + tokens_output
            analytics.total_cost = (analytics.total_cost or 0) + cost
        else:
            analytics = TenantAnalytics(
                tenant_id=tenant_id,
                period="daily",
                period_start=today,
                total_tokens_used=tokens_input + tokens_output,
                total_cost=cost,
            )
            self.db.add(analytics)

        self.db.commit()
