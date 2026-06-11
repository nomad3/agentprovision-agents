"""Chat-triggered desktop-control intent routing pins.

The generated Luna prompt owns the safe loop, but chat routing still needs a
positive desktop intent so unbound operator messages can select an agent with
desktop tool groups instead of falling back to generic chat.
"""

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
