"""Tests for Phase 4: Whitelabel System."""
import pytest
import os

os.environ["TESTING"] = "True"


def test_tenant_branding_model():
    """Test TenantBranding model has required fields."""
    from app.models.tenant_branding import TenantBranding

    assert hasattr(TenantBranding, 'id')
    assert hasattr(TenantBranding, 'tenant_id')
    assert hasattr(TenantBranding, 'company_name')
    assert hasattr(TenantBranding, 'logo_url')
    assert hasattr(TenantBranding, 'logo_dark_url')
    assert hasattr(TenantBranding, 'favicon_url')
    assert hasattr(TenantBranding, 'support_email')
    assert hasattr(TenantBranding, 'primary_color')
    assert hasattr(TenantBranding, 'secondary_color')
    assert hasattr(TenantBranding, 'accent_color')
    assert hasattr(TenantBranding, 'background_color')
    assert hasattr(TenantBranding, 'sidebar_bg')
    assert hasattr(TenantBranding, 'ai_assistant_name')
    assert hasattr(TenantBranding, 'ai_assistant_persona')
    assert hasattr(TenantBranding, 'custom_domain')
    assert hasattr(TenantBranding, 'domain_verified')
    assert hasattr(TenantBranding, 'industry')
    assert hasattr(TenantBranding, 'compliance_mode')


def test_tenant_features_model():
    """Test TenantFeatures model has required fields."""
    from app.models.tenant_features import TenantFeatures

    assert hasattr(TenantFeatures, 'id')
    assert hasattr(TenantFeatures, 'tenant_id')
    # Core Features
    assert hasattr(TenantFeatures, 'agents_enabled')
    assert hasattr(TenantFeatures, 'agent_groups_enabled')
    assert hasattr(TenantFeatures, 'datasets_enabled')
    assert hasattr(TenantFeatures, 'chat_enabled')
    assert hasattr(TenantFeatures, 'multi_llm_enabled')
    assert hasattr(TenantFeatures, 'agent_memory_enabled')
    # AI Intelligence
    assert hasattr(TenantFeatures, 'ai_insights_enabled')
    assert hasattr(TenantFeatures, 'ai_recommendations_enabled')
    assert hasattr(TenantFeatures, 'ai_anomaly_detection')
    # Limits
    assert hasattr(TenantFeatures, 'max_agents')
    assert hasattr(TenantFeatures, 'max_agent_groups')
    assert hasattr(TenantFeatures, 'monthly_token_limit')
    assert hasattr(TenantFeatures, 'storage_limit_gb')
    # UI
    assert hasattr(TenantFeatures, 'hide_agentprovision_branding')
    assert hasattr(TenantFeatures, 'plan_type')


def test_tenant_analytics_model():
    """Test TenantAnalytics model has required fields."""
    from app.models.tenant_analytics import TenantAnalytics

    assert hasattr(TenantAnalytics, 'id')
    assert hasattr(TenantAnalytics, 'tenant_id')
    assert hasattr(TenantAnalytics, 'period')
    assert hasattr(TenantAnalytics, 'period_start')
    # Usage Metrics
    assert hasattr(TenantAnalytics, 'total_messages')
    assert hasattr(TenantAnalytics, 'total_tasks')
    assert hasattr(TenantAnalytics, 'total_tokens_used')
    assert hasattr(TenantAnalytics, 'total_cost')
    # AI-Generated
    assert hasattr(TenantAnalytics, 'ai_insights')
    assert hasattr(TenantAnalytics, 'ai_recommendations')
    assert hasattr(TenantAnalytics, 'ai_forecast')


def test_branding_api_routes():
    """Test branding API routes exist."""
    from app.api.v1 import branding

    assert hasattr(branding, 'router')
    assert hasattr(branding, 'get_branding')
    assert hasattr(branding, 'update_branding')


def test_features_api_routes():
    """Test features API routes exist."""
    from app.api.v1 import features

    assert hasattr(features, 'router')
    assert hasattr(features, 'get_features')
    assert hasattr(features, 'check_feature')


def test_tenant_analytics_api_routes():
    """Test tenant analytics API routes exist."""
    from app.api.v1 import tenant_analytics

    assert hasattr(tenant_analytics, 'router')
    assert hasattr(tenant_analytics, 'get_analytics_summary')
    assert hasattr(tenant_analytics, 'get_analytics_history')


def test_agent_extended_fields():
    """Test Agent model has integration fields."""
    from app.models.agent import Agent

    assert hasattr(Agent, 'llm_config_id')
    assert hasattr(Agent, 'memory_config')


def test_chat_session_extended_fields():
    """Test ChatSession model has integration fields."""
    from app.models.chat import ChatSession

    assert hasattr(ChatSession, 'agent_group_id')
    assert hasattr(ChatSession, 'root_task_id')
    assert hasattr(ChatSession, 'memory_context')


def test_chat_message_extended_fields():
    """Test ChatMessage model has integration fields."""
    from app.models.chat import ChatMessage

    assert hasattr(ChatMessage, 'agent_id')
    assert hasattr(ChatMessage, 'task_id')
    assert hasattr(ChatMessage, 'reasoning')
    assert hasattr(ChatMessage, 'confidence')
    assert hasattr(ChatMessage, 'tokens_used')


def test_tenant_extended_fields():
    """Test Tenant model has integration fields."""
    from app.models.tenant import Tenant

    assert hasattr(Tenant, 'default_llm_config_id')
    assert hasattr(Tenant, 'branding')
    assert hasattr(Tenant, 'features')


def test_agent_kit_extended_fields():
    """Test AgentKit model has integration fields."""
    from app.models.agent_kit import AgentKit

    assert hasattr(AgentKit, 'kit_type')
    assert hasattr(AgentKit, 'default_agents')
    assert hasattr(AgentKit, 'default_hierarchy')
    assert hasattr(AgentKit, 'industry')


def test_enhanced_chat_service():
    """Test EnhancedChatService exists with required methods."""
    from app.services.enhanced_chat import EnhancedChatService

    assert hasattr(EnhancedChatService, 'create_session_with_orchestration')
    assert hasattr(EnhancedChatService, 'post_message_with_memory')
    assert hasattr(EnhancedChatService, 'select_llm_for_task')


def test_chat_enhanced_routes():
    """Test chat API has enhanced routes."""
    from app.api.v1 import chat

    assert hasattr(chat, 'create_session_enhanced')
    assert hasattr(chat, 'post_message_enhanced')


def test_llm_router_enhanced():
    """Test LLMRouter has enhanced methods."""
    from app.services.llm.router import LLMRouter

    assert hasattr(LLMRouter, 'get_tenant_config')
    assert hasattr(LLMRouter, 'track_usage')
