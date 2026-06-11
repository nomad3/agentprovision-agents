"""Chat-triggered desktop-control intent routing pins.

The generated Luna prompt owns the safe loop, but chat routing still needs a
positive desktop intent so unbound operator messages can select an agent with
desktop tool groups instead of falling back to generic chat.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.agent_router import _infer_task_type
from app.services.embedding_service import INTENT_DEFINITIONS


def test_desktop_intent_definition_routes_to_desktop_tool_groups():
    matches = [
        intent
        for intent in INTENT_DEFINITIONS
        if "desktop" in intent["tools"] or "desktop_control" in intent["tools"]
    ]

    assert len(matches) == 1
    intent = matches[0]
    assert intent["tier"] == "full"
    assert intent["mutation"] is True
    assert set(intent["tools"]) == {"desktop_observe", "desktop_control"}
    assert "macos" in intent["name"]
    assert "app control" in intent["name"]


def test_desktop_task_type_inference_for_macos_app_control():
    assert _infer_task_type("Luna, click the Send button in WhatsApp") == "desktop"
    assert _infer_task_type("Control the macOS app with the keyboard") == "desktop"
    assert _infer_task_type("Show the desktop app screen before acting") == "desktop"


class _Query:
    def __init__(self, *, first=None, all_rows=None):
        self._first = first
        self._all_rows = all_rows or []
        self.first_count = 0
        self.all_count = 0

    def filter(self, *args, **kwargs):  # noqa: ARG002
        return self

    def first(self):
        self.first_count += 1
        return self._first

    def all(self):
        self.all_count += 1
        return self._all_rows


class _Db:
    def __init__(self, *, agent_first=None, all_agents=None):
        self.agent_query = _Query(first=agent_first, all_rows=all_agents or [])
        self.tenant_features_query = _Query(first=None)
        self.fallback_query = _Query(first=None)
        self.execute = MagicMock()
        self.execute.return_value.first.return_value = None
        self.rollback = MagicMock()
        self.commit = MagicMock()

    def query(self, model):
        table = getattr(model, "__tablename__", "")
        if table == "tenant_features":
            return self.tenant_features_query
        if table == "agents":
            return self.agent_query
        return self.fallback_query


def _agent(name: str, tool_groups: list[str] | None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        tenant_id=uuid.uuid4(),
        config={},
        tool_groups=tool_groups,
        default_model_tier="full",
        memory_domains=[],
    )


def _patch_router_for_fast_dispatch(monkeypatch, agent_router, *, intent):
    monkeypatch.setattr(
        agent_router.platform_safety_io,
        "consult_with_audit",
        lambda *a, **kw: SimpleNamespace(decision="allow"),
    )
    monkeypatch.setattr(
        agent_router.agent_value_set_io,
        "consult_routing",
        lambda *a, **kw: SimpleNamespace(decision="allow"),
    )
    monkeypatch.setattr(
        agent_router.safety_trust,
        "get_agent_trust_profile",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(agent_router, "match_intent", lambda *a, **kw: intent)
    monkeypatch.setattr(agent_router, "_greeting_template", lambda *a, **kw: None)
    monkeypatch.setattr(agent_router, "_should_use_local_path", lambda *a, **kw: False)
    monkeypatch.setattr(agent_router, "_get_active_cooldowns", lambda *a, **kw: set())
    monkeypatch.setattr(agent_router, "_resolve_cli_chain", lambda *a, **kw: ["opencode"])
    monkeypatch.setattr(agent_router, "_build_memory_context", lambda *a, **kw: {})
    monkeypatch.setattr(
        agent_router.rl_experience_service,
        "log_experience",
        lambda *a, **kw: None,
    )


def test_unbound_desktop_prompt_selects_existing_desktop_agent(monkeypatch):
    from app.services import agent_router

    desktop_agent = _agent(
        "Luna Supervisor",
        ["knowledge", "desktop_observe", "desktop_control"],
    )
    generic_agent = _agent("Knowledge Agent", ["knowledge"])
    db = _Db(agent_first=None, all_agents=[generic_agent, desktop_agent])
    intent = {
        "name": "operate or observe a macos desktop app",
        "tier": "full",
        "tools": ["desktop_observe", "desktop_control"],
        "mutation": True,
    }
    _patch_router_for_fast_dispatch(monkeypatch, agent_router, intent=intent)

    calls: list[dict] = []

    def _run_agent_session(*args, **kwargs):  # noqa: ARG001
        calls.append(kwargs)
        return "ok", {"platform": "opencode"}

    monkeypatch.setattr(agent_router, "run_agent_session", _run_agent_session)

    response, _metadata = agent_router.route_and_execute(
        db,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        message="Luna, click the Send button in WhatsApp",
        agent_slug="luna",
        db_session_memory={"chat_session_id": str(uuid.uuid4())},
    )

    assert response == "ok"
    assert calls[0]["agent_slug"] == "luna-supervisor"
    assert calls[0]["agent_tool_groups"] == desktop_agent.tool_groups
    assert calls[0]["agent_memory_domains"] == []


def test_non_desktop_prompt_does_not_select_desktop_agent(monkeypatch):
    from app.services import agent_router

    db = _Db(agent_first=None)
    _patch_router_for_fast_dispatch(monkeypatch, agent_router, intent=None)

    calls: list[dict] = []

    def _run_agent_session(*args, **kwargs):  # noqa: ARG001
        calls.append(kwargs)
        return "ok", {"platform": "opencode"}

    monkeypatch.setattr(agent_router, "run_agent_session", _run_agent_session)

    response, _metadata = agent_router.route_and_execute(
        db,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        message="Summarize this account note for me",
        agent_slug="luna",
        db_session_memory={"chat_session_id": str(uuid.uuid4())},
    )

    assert response == "ok"
    assert calls[0]["agent_slug"] == "luna"
    assert calls[0]["agent_tool_groups"] is None
    assert db.agent_query.all_count == 0


def test_bound_non_desktop_agent_is_not_overridden_by_desktop_intent(monkeypatch):
    from app.services import agent_router

    bound_agent = _agent("Finance Agent", ["data", "reports"])
    db = _Db(agent_first=bound_agent)
    intent = {
        "name": "operate or observe a macos desktop app",
        "tier": "full",
        "tools": ["desktop_observe", "desktop_control"],
        "mutation": True,
    }
    _patch_router_for_fast_dispatch(monkeypatch, agent_router, intent=intent)

    calls: list[dict] = []

    def _run_agent_session(*args, **kwargs):  # noqa: ARG001
        calls.append(kwargs)
        return "ok", {"platform": "opencode"}

    monkeypatch.setattr(agent_router, "run_agent_session", _run_agent_session)

    response, _metadata = agent_router.route_and_execute(
        db,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        message="Use the desktop app to compare revenue",
        agent_slug="finance-agent",
        db_session_memory={"chat_session_id": str(uuid.uuid4())},
    )

    assert response == "ok"
    assert calls[0]["agent_slug"] == "finance-agent"
    assert calls[0]["agent_tool_groups"] == ["data", "reports"]
    assert db.agent_query.all_count == 0
