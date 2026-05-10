"""Tests for ``app.services.agent_token`` — Phase 4 commit 1.

Covers the SR items relevant to mint/verify:
  - SR-3: parent_chain hard-capped at 3 elements at mint time
  - SR-3 regression guard: JWT size budget < 4 KB even with worst-case
    50-tool scope + 3-element parent_chain
  - SR-11: kind=='agent_token' AND sub.startswith('agent:') double-check
  - Standard JWT hygiene: round-trip, expiry, tampered signature, missing
    fields rejected
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

pytest.importorskip("jose")

from jose import ExpiredSignatureError, jwt

from app.core.config import settings
from app.services.agent_token import (
    mint_agent_token,
    verify_agent_token,
)


def _claim_kwargs(**overrides):
    base = dict(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        parent_workflow_id="wf-test-1",
        scope=None,
        parent_chain=(),
        heartbeat_timeout_seconds=240,
    )
    base.update(overrides)
    return base


def test_round_trip_mint_and_verify():
    kwargs = _claim_kwargs(scope=["recall_memory", "record_observation"])
    tok = mint_agent_token(**kwargs)
    claims = verify_agent_token(tok)
    assert claims["kind"] == "agent_token"
    assert claims["sub"] == f"agent:{kwargs['agent_id']}"
    assert claims["tenant_id"] == kwargs["tenant_id"]
    assert claims["task_id"] == kwargs["task_id"]
    assert claims["scope"] == ["recall_memory", "record_observation"]
    assert claims["parent_chain"] == []


def test_scope_none_preserved():
    """``scope=None`` means 'no per-call check', distinct from empty list."""
    tok = mint_agent_token(**_claim_kwargs(scope=None))
    claims = verify_agent_token(tok)
    assert claims["scope"] is None


def test_scope_empty_list_preserved():
    """Empty list means 'no tools allowed' — distinct from None."""
    tok = mint_agent_token(**_claim_kwargs(scope=[]))
    claims = verify_agent_token(tok)
    assert claims["scope"] == []


def test_expired_token_raises():
    """ExpiredSignatureError surfaces verbatim (don't wrap as ValueError)."""
    kwargs = _claim_kwargs()
    # Mint with negative TTL — already expired the moment we encode.
    with patch("app.services.agent_token.time.time", return_value=time.time() - 10000):
        tok = mint_agent_token(heartbeat_timeout_seconds=1, **{
            k: v for k, v in kwargs.items() if k != "heartbeat_timeout_seconds"
        })
    with pytest.raises(ExpiredSignatureError):
        verify_agent_token(tok)


def test_tampered_signature_rejected():
    tok = mint_agent_token(**_claim_kwargs())
    # Flip last char of signature.
    head, _, sig = tok.rpartition(".")
    bad_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    with pytest.raises(ValueError):
        verify_agent_token(f"{head}.{bad_sig}")


def test_missing_kind_rejected():
    """Token signed with our secret but missing 'kind' must be rejected.

    Defends against the case where someone builds a JWT with our SECRET_KEY
    that doesn't carry our kind discriminator (e.g. a future bug elsewhere
    in the codebase).
    """
    payload = {
        "sub": "agent:abc",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        # NO kind field
    }
    tok = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(ValueError, match="kind"):
        verify_agent_token(tok)


def test_kind_not_agent_token_rejected():
    """SR-11: a regular login token (kind=access or kind=user) must NOT
    cross into the agent-token tier. Defence-in-depth on the auth-tier
    classifier."""
    payload = {
        "sub": "agent:abc",
        "kind": "access",  # wrong kind
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    tok = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(ValueError, match="agent_token"):
        verify_agent_token(tok)


def test_sub_not_agent_prefix_rejected():
    """SR-11: sub must start with 'agent:'. A token whose kind says
    agent_token but whose sub is an email or a tenant id must be refused."""
    payload = {
        "sub": "user@example.com",  # not agent:...
        "kind": "agent_token",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    tok = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(ValueError, match="agent:"):
        verify_agent_token(tok)


def test_parent_chain_length_above_max_rejected_at_mint():
    """SR-3: mint refuses to embed parent_chain longer than
    MAX_FALLBACK_DEPTH=3. Length 3 is admissible (the §3.1 gate refuses
    *at dispatch* but the token shape stays clean); length 4+ means we
    already mis-counted upstream — fail loud."""
    chain_too_long = [str(uuid.uuid4()) for _ in range(4)]
    with pytest.raises(ValueError, match="parent_chain too long"):
        mint_agent_token(**_claim_kwargs(parent_chain=chain_too_long))


def test_parent_chain_length_at_max_accepted():
    """Length exactly 3 is the boundary case — must round-trip cleanly."""
    chain = [str(uuid.uuid4()) for _ in range(3)]
    tok = mint_agent_token(**_claim_kwargs(parent_chain=chain))
    claims = verify_agent_token(tok)
    assert claims["parent_chain"] == chain


def test_jwt_size_budget_under_4kb_with_worst_case_scope():
    """SR-3 regression guard: JWT must stay under 4 KB even with the
    worst-case combination of a 50-tool scope and a 3-element
    parent_chain. 4 KB is a generous bound — typical HTTP header
    limits are 8 KB total, but Cloudflare and many proxies enforce
    per-header soft limits in the 4-8 KB range. Stay well clear."""
    fifty_tools = [f"tool_name_{i}" for i in range(50)]
    chain = [str(uuid.uuid4()) for _ in range(3)]
    tok = mint_agent_token(**_claim_kwargs(scope=fifty_tools, parent_chain=chain))
    # The token is base64url-encoded; len() is bytes-on-the-wire.
    assert len(tok) < 4096, (
        f"agent_token grew to {len(tok)} bytes — review claim packing"
    )


def test_parent_workflow_id_optional():
    tok = mint_agent_token(**_claim_kwargs(parent_workflow_id=None))
    claims = verify_agent_token(tok)
    assert claims.get("parent_workflow_id") is None


def test_exp_is_2x_heartbeat_timeout():
    """Design §8 step 1: exp = heartbeat_timeout * 2.

    Decode without expiry verification to inspect raw claim arithmetic
    independently of when the test runs.
    """
    fixed_now = int(time.time())
    tok = mint_agent_token(**_claim_kwargs(heartbeat_timeout_seconds=240))
    claims = jwt.decode(
        tok,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"verify_exp": False},
    )
    # iat/exp are populated by mint_agent_token(); allow ±2s slack.
    assert abs(claims["iat"] - fixed_now) <= 2
    assert claims["exp"] - claims["iat"] == 480
