"""Per-request model override using ADK's before_model_callback.

Reads llm_config from session state (passed via state_delta by the API)
and overrides llm_request.model to route to the tenant's chosen provider.

Usage: Register on every Agent definition:
    from config.model_callback import llm_model_callback
    agent = Agent(..., before_model_callback=llm_model_callback)
"""
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse


# LiteLLM provider prefixes for model string formatting
PROVIDER_PREFIXES = {
    "anthropic_llm": "anthropic",
    # Future providers:
    # "openai_llm": "openai",
    # "deepseek_llm": "deepseek",
}


def llm_model_callback(
    ctx: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Override model per-request based on tenant's llm_config in session state.

    The API passes llm_config in state_delta:
        {"provider": "anthropic_llm", "model": "claude-sonnet-4-5", "api_key": "sk-..."}

    For Gemini: sets llm_request.model to the model string (native ADK).
    For other providers: sets llm_request.model to "provider/model" (LiteLLM format)
        and passes api_key via llm_request.config.
    """
    llm_config = ctx.state.get("llm_config")
    if not llm_config:
        return None  # No override — use default Gemini from settings.adk_model

    provider = llm_config.get("provider")
    model = llm_config.get("model")
    api_key = llm_config.get("api_key")

    if not provider or not model:
        return None  # Incomplete config — use default

    if provider == "gemini_llm":
        # Native Gemini — just override the model string
        llm_request.model = model
        return None

    # Non-Gemini provider — use LiteLLM format
    prefix = PROVIDER_PREFIXES.get(provider)
    if not prefix:
        return None  # Unknown provider — use default

    llm_request.model = f"{prefix}/{model}"

    # Pass API key per-request (thread-safe, no os.environ mutation)
    if api_key:
        if not hasattr(llm_request, "config") or llm_request.config is None:
            llm_request.config = {}
        if isinstance(llm_request.config, dict):
            llm_request.config["api_key"] = api_key
        else:
            # config may be a pydantic model — try attribute setting
            try:
                llm_request.config.api_key = api_key
            except AttributeError:
                pass

    return None
