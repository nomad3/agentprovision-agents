import httpx
import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class CopilotStudioClient:
    """
    Client for interacting with Microsoft Copilot Studio agents via Direct Line API.
    """
    def __init__(self, token: str, bot_id: str):
        self.token = token
        self.bot_id = bot_id
        self.base_url = "https://directline.botframework.com/v3/directline"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def start_conversation(self) -> str:
        """Starts a new conversation and returns the conversationId."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/conversations", headers=self.headers)
            resp.raise_for_status()
            return resp.json()["conversationId"]

    async def send_message(self, conversation_id: str, text: str, user_id: str = "agentprovision-user"):
        """Sends a message to the bot."""
        activity = {
            "type": "message",
            "from": {"id": user_id},
            "text": text
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/conversations/{conversation_id}/activities",
                headers=self.headers,
                json=activity
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def get_activities(self, conversation_id: str, watermark: Optional[str] = None):
        """Retrieves activities (responses) from the bot."""
        url = f"{self.base_url}/conversations/{conversation_id}/activities"
        if watermark:
            url += f"?watermark={watermark}"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

async def manage_copilot_studio_agent(
    tenant_id: str, 
    bot_id: str, 
    token: str, 
    action: str, 
    message: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    MCP tool to manage and interact with a Copilot Studio agent.
    
    Actions:
    - 'start': Start a new conversation.
    - 'send': Send a message to an existing conversation and wait for response.
    """
    client = CopilotStudioClient(token, bot_id)
    
    try:
        if action == "start":
            conv_id = await client.start_conversation()
            return {"status": "success", "conversation_id": conv_id}
        
        elif action == "send":
            if not conversation_id or not message:
                return {"status": "error", "message": "Missing conversation_id or message"}
            
            await client.send_message(conversation_id, message)
            
            # Polling for response (simplified for this example)
            import asyncio
            responses = []
            for _ in range(5): # Try 5 times
                await asyncio.sleep(2)
                activities = await client.get_activities(conversation_id)
                for act in activities.get("activities", []):
                    if act.get("from", {}).get("id") == bot_id and act.get("type") == "message":
                        responses.append(act.get("text"))
                if responses:
                    break
            
            return {
                "status": "success",
                "responses": responses
            }
            
        return {"status": "error", "message": f"Unknown action: {action}"}
        
    except Exception as e:
        logger.exception("Copilot Studio interaction failed")
        return {"status": "error", "message": str(e)}
