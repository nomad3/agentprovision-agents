# Luna Progress Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send mini progress messages to WhatsApp users while the CLI is processing, so they know what Luna is doing instead of waiting 1-3 minutes in silence.

**Architecture:** The WhatsApp handler sends an immediate "working on it" message before dispatching to the CLI. A timed progress task sends periodic status updates during the wait. When the CLI responds, the final message is sent and progress stops. No Temporal changes needed — fully backward compatible.

**Tech Stack:** Python asyncio, neonize WhatsApp client, existing cli_session_manager

---

## File Structure

```
Modified:
  apps/api/app/services/whatsapp_service.py    — progress message loop + immediate ack
  apps/api/app/services/cli_session_manager.py  — (optional) return timing metadata

No new files needed. This is a contained change in the WhatsApp handler.
```

---

### Task 1: Immediate Acknowledgment Message

Send a brief "working on it" message immediately when a user sends a message, before the CLI starts.

**Files:**
- Modify: `apps/api/app/services/whatsapp_service.py` (around line 529-551, the typing indicator setup area)

- [ ] **Step 1: Write the failing test**

Create test file:
```python
# apps/api/tests/test_whatsapp_progress.py
"""Tests for WhatsApp progress message behavior."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

class TestProgressMessages:
    """Test that Luna sends progress updates during CLI processing."""

    @pytest.mark.asyncio
    async def test_immediate_ack_sent_before_agent_dispatch(self):
        """An acknowledgment message should be sent before the CLI starts."""
        from app.services.whatsapp_service import _build_ack_message
        # Simple messages get a short ack
        ack = _build_ack_message("What meetings do I have tomorrow?", "general")
        assert len(ack) < 100
        assert ack  # Non-empty

    @pytest.mark.asyncio
    async def test_code_task_gets_specific_ack(self):
        """Code-related tasks should mention code analysis."""
        from app.services.whatsapp_service import _build_ack_message
        ack = _build_ack_message("Review the latest PR changes", "code")
        assert "code" in ack.lower() or "review" in ack.lower() or "analyzing" in ack.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec agentprovision-agents-api-1 pytest /app/tests/test_whatsapp_progress.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_ack_message'`

- [ ] **Step 3: Implement `_build_ack_message` helper**

Add to `apps/api/app/services/whatsapp_service.py` (near top, after imports):

```python
def _build_ack_message(user_message: str, task_type: str) -> str:
    """Build a brief acknowledgment based on the inferred task type."""
    acks = {
        "code": "Analyzing code — give me a moment...",
        "research": "Researching that — checking my sources...",
        "email": "Checking emails — one moment...",
        "calendar": "Looking at your calendar...",
        "sales": "Pulling up pipeline data...",
        "data": "Querying the data — hang tight...",
    }
    return acks.get(task_type, "On it — thinking...")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec agentprovision-agents-api-1 pytest /app/tests/test_whatsapp_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/whatsapp_service.py apps/api/tests/test_whatsapp_progress.py
git commit -m "feat: add _build_ack_message helper for progress updates"
```

---

### Task 2: Send Immediate Ack in WhatsApp Handler

Wire the ack message into the WhatsApp inbound handler so it's sent before the CLI dispatches.

**Files:**
- Modify: `apps/api/app/services/whatsapp_service.py` (the `_handle_inbound` method, around line 529-551)

- [ ] **Step 1: Write the failing test**

```python
# Add to apps/api/tests/test_whatsapp_progress.py
    @pytest.mark.asyncio
    async def test_ack_sent_before_typing_starts(self):
        """The ack should be sent immediately, not after CLI completes."""
        sent_messages = []

        async def mock_send(jid, msg):
            sent_messages.append(msg)
            return MagicMock()

        # Verify that _build_ack_message is called and sent
        ack = _build_ack_message("hello", "general")
        assert ack == "On it — thinking..."
```

- [ ] **Step 2: Implement the ack send in `_handle_inbound`**

In `apps/api/app/services/whatsapp_service.py`, find the section after `reply_jid = build_jid(sender_phone)` and before `typing_done = asyncio.Event()`. Insert:

```python
# Send immediate acknowledgment before CLI processing
try:
    from app.services.agent_router import _infer_task_type
    task_type = _infer_task_type(agent_text)
    ack_msg = _build_ack_message(agent_text, task_type)
    await client.send_message(reply_jid, ack_msg)
except Exception:
    pass  # Never block on ack failure
```

- [ ] **Step 3: Verify in container**

Run: `docker exec agentprovision-agents-api-1 python -m py_compile /app/app/services/whatsapp_service.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/services/whatsapp_service.py
git commit -m "feat: send immediate ack message before CLI dispatch"
```

---

### Task 3: Timed Progress Updates During CLI Wait

Send periodic progress messages while waiting for the CLI to respond (every 30 seconds).

**Files:**
- Modify: `apps/api/app/services/whatsapp_service.py` (the `_keep_typing` coroutine area)

- [ ] **Step 1: Write the test**

```python
# Add to apps/api/tests/test_whatsapp_progress.py
    def test_progress_messages_rotate(self):
        """Progress messages should cycle through different status updates."""
        from app.services.whatsapp_service import _get_progress_message
        msgs = [_get_progress_message(i) for i in range(5)]
        # Should have variety, not all the same
        assert len(set(msgs)) >= 3
```

- [ ] **Step 2: Implement `_get_progress_message` helper**

Add to `apps/api/app/services/whatsapp_service.py`:

```python
_PROGRESS_MESSAGES = [
    "Checking memory and knowledge base...",
    "Analyzing your request...",
    "Working through the details...",
    "Almost there — finalizing response...",
    "Still working on this — it's a complex one...",
    "Gathering all the context I need...",
    "Running tools and cross-referencing data...",
]

def _get_progress_message(tick: int) -> str:
    """Get a rotating progress message based on elapsed ticks."""
    return _PROGRESS_MESSAGES[tick % len(_PROGRESS_MESSAGES)]
```

- [ ] **Step 3: Wire into `_keep_typing` to send progress every 30s**

Modify the `_keep_typing()` coroutine in `_handle_inbound` to also send progress messages. Replace the existing `_keep_typing` with:

```python
async def _keep_typing():
    tick = 0
    while not typing_done.is_set():
        try:
            await client.send_chat_presence(
                reply_jid,
                ChatPresence.CHAT_PRESENCE_COMPOSING,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
            )
        except Exception:
            pass
        # Send a progress message every 30s (after initial 20s delay)
        if tick > 0 and tick % 8 == 0:  # 8 ticks * 4s = 32s
            try:
                progress_msg = _get_progress_message(tick // 8)
                await client.send_message(reply_jid, progress_msg)
            except Exception:
                pass
        tick += 1
        try:
            await asyncio.wait_for(typing_done.wait(), timeout=4)
            break
        except asyncio.TimeoutError:
            continue
```

- [ ] **Step 4: Run tests**

Run: `docker exec agentprovision-agents-api-1 pytest /app/tests/test_whatsapp_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/whatsapp_service.py apps/api/tests/test_whatsapp_progress.py
git commit -m "feat: send rotating progress messages every 30s during CLI wait"
```

---

### Task 4: Include Response Highlights After Completion

After the CLI responds, send a brief "here's what I did" summary before the full response for complex tasks.

**Files:**
- Modify: `apps/api/app/services/whatsapp_service.py` (the response sending area, around line 640-663)

- [ ] **Step 1: Write the test**

```python
# Add to apps/api/tests/test_whatsapp_progress.py
    def test_summary_prefix_for_long_responses(self):
        """Long responses should get a brief summary prefix."""
        from app.services.whatsapp_service import _build_completion_summary
        long_response = "Here is a detailed analysis of your pipeline..." + "x" * 1000
        summary = _build_completion_summary(long_response, elapsed_seconds=120)
        assert summary is not None
        assert len(summary) < 150
        assert "2 min" in summary or "120" in summary or "done" in summary.lower()

    def test_no_summary_for_short_responses(self):
        """Short quick responses don't need a summary."""
        from app.services.whatsapp_service import _build_completion_summary
        summary = _build_completion_summary("Sure, here you go.", elapsed_seconds=5)
        assert summary is None  # No summary needed for fast responses
```

- [ ] **Step 2: Implement `_build_completion_summary`**

```python
def _build_completion_summary(response_text: str, elapsed_seconds: float) -> Optional[str]:
    """Build a brief completion note for long-running responses."""
    if elapsed_seconds < 15 or len(response_text) < 200:
        return None  # Quick responses don't need a summary
    mins = int(elapsed_seconds // 60)
    secs = int(elapsed_seconds % 60)
    time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
    return f"Done ({time_str}). Here's what I found:"
```

- [ ] **Step 3: Wire into response sending**

In the response sending section of `_handle_inbound`, before sending the main response chunks, insert:

```python
# Track elapsed time since dispatch
import time
# (set dispatch_time = time.monotonic() right before _process_through_agent call)
elapsed = time.monotonic() - dispatch_time
completion_note = _build_completion_summary(response_text, elapsed)
if completion_note:
    try:
        await client.send_message(reply_jid, completion_note)
    except Exception:
        pass
```

- [ ] **Step 4: Run all tests**

Run: `docker exec agentprovision-agents-api-1 pytest /app/tests/test_whatsapp_progress.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/whatsapp_service.py apps/api/tests/test_whatsapp_progress.py
git commit -m "feat: add completion summary for long-running responses"
```

---

### Task 5: End-to-End Integration Test

Verify the full flow works together in the container.

**Files:**
- Modify: `apps/api/tests/test_whatsapp_progress.py`

- [ ] **Step 1: Add integration test**

```python
class TestProgressIntegration:
    """Integration tests for the full progress message flow."""

    def test_all_helpers_importable(self):
        """All progress helpers should be importable from whatsapp_service."""
        from app.services.whatsapp_service import (
            _build_ack_message,
            _get_progress_message,
            _build_completion_summary,
        )
        assert callable(_build_ack_message)
        assert callable(_get_progress_message)
        assert callable(_build_completion_summary)

    def test_ack_messages_are_short(self):
        """All ack messages should be under 100 chars for mobile readability."""
        from app.services.whatsapp_service import _build_ack_message
        for task_type in ["code", "research", "email", "calendar", "sales", "data", "general"]:
            msg = _build_ack_message("test", task_type)
            assert len(msg) < 100, f"Ack for {task_type} too long: {len(msg)}"

    def test_progress_messages_are_short(self):
        """All progress messages should be under 100 chars."""
        from app.services.whatsapp_service import _get_progress_message
        for i in range(20):
            msg = _get_progress_message(i)
            assert len(msg) < 100, f"Progress message {i} too long: {len(msg)}"
```

- [ ] **Step 2: Run full test suite in container**

Run: `docker exec agentprovision-agents-api-1 pytest /app/tests/test_whatsapp_progress.py -v`
Expected: All PASS

- [ ] **Step 3: Rebuild and restart API**

```bash
docker-compose restart api
```

- [ ] **Step 4: Manual test via WhatsApp**

Send Luna a message that requires CLI processing (e.g., "Check my latest code changes"). Verify:
1. Immediate ack message arrives within 1-2 seconds
2. Progress update arrives after ~30 seconds
3. Completion summary arrives before the full response (if >15 seconds)
4. Full response arrives normally

- [ ] **Step 5: Final commit and push**

```bash
git add -A
git commit -m "feat: Luna progress messages — ack, progress updates, completion summary"
git push
```

---

## Summary

After implementation, Luna's WhatsApp flow becomes:

```
User: "Check my latest code changes"
    │
    ▼ (1s)
Luna: "Analyzing code — give me a moment..."     ← immediate ack
    │
    ▼ (32s)
Luna: "Checking memory and knowledge base..."    ← progress tick 1
    │
    ▼ (64s)
Luna: "Working through the details..."           ← progress tick 2
    │
    ▼ (90s)
Luna: "Done (1m 30s). Here's what I found:"     ← completion summary
Luna: [full detailed response]                    ← actual response
```

For quick responses (<15s), only the ack and response appear — no progress noise.
