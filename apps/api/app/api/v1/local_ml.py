"""Local ML API — manage Ollama models and inference."""

import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from app.api import deps
from app.core.config import settings

router = APIRouter()


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    """Internal-key auth for MCP-server tools that need local LLM
    generation (e.g. sales.draft_outreach).
    """
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


class GenerateRequest(BaseModel):
    prompt: str
    tenant_id: Optional[str] = None  # accepted for future per-tenant routing
    model: Optional[str] = None
    system: Optional[str] = ""
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=1, le=8000)
    timeout: float = Field(default=45.0, ge=1.0, le=300.0)
    response_format: Optional[str] = None  # 'json' for JSON-mode Ollama


@router.post("/generate")
def generate(
    body: GenerateRequest,
    _auth: None = Depends(_verify_internal_key),
):
    """Generate text via the local Ollama instance.

    Bridges MCP-server tools (sales.draft_outreach, future enrichment
    callers) to the existing ``local_inference.generate_sync`` helper.
    sales.py was already calling this endpoint — but it didn't exist,
    so every draft_outreach silently fell back to its template. Adding
    the bridge makes personalised cold emails actually work.

    Gated by X-Internal-Key. The cloudflared ingress blocks
    /api/v1/*/internal($|/) from the public internet; this endpoint
    lives at /local-ml/generate (no /internal segment), so a key leak
    would expose it externally. Same risk surface as
    /agent-tokens/mint — acceptable given the small blast radius
    (returns text, no side effects).
    """
    from app.services.local_inference import generate_sync, DEFAULT_MODEL
    text = generate_sync(
        prompt=body.prompt,
        model=body.model,
        system=body.system or "",
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        timeout=body.timeout,
        response_format=body.response_format,
    )
    if text is None:
        # Ollama unreachable or non-200 — caller falls back to template.
        return {"error": "local inference unavailable", "text": "", "model": body.model or DEFAULT_MODEL}
    return {"text": text, "model": body.model or DEFAULT_MODEL}


@router.get("/status")
async def get_status(current_user=Depends(deps.get_current_active_user)):
    """Check local ML inference availability."""
    from app.services.local_inference import is_available, list_models, OLLAMA_BASE_URL
    available = await is_available()
    models = await list_models() if available else []
    return {
        "available": available,
        "ollama_url": OLLAMA_BASE_URL,
        "models": models,
        "model_count": len(models),
    }


@router.post("/pull")
async def pull_model(
    model_name: str = "gemma4",
    current_user=Depends(deps.get_current_active_user),
):
    """Pull a model to Ollama."""
    from app.services.local_inference import pull_model
    success = await pull_model(model_name)
    return {"model": model_name, "success": success}


@router.post("/score-test")
async def test_quality_scoring(
    user_message: str = "What is 2+2?",
    agent_response: str = "4",
    current_user=Depends(deps.get_current_active_user),
):
    """Test the auto-quality scorer."""
    from app.services.local_inference import score_response_quality
    result = await score_response_quality(user_message, agent_response)
    return {"result": result}
