import asyncio
import logging
import os
import uuid
import base64
import json
import time
from typing import Dict, Optional, List
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer

# Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LUNA_API_URL = os.getenv("LUNA_API_URL", "http://api:8000/api/v1")
DEVICE_BRIDGE_TOKEN = os.getenv("DEVICE_BRIDGE_TOKEN", "")
DEVICE_ID = os.getenv("DEVICE_ID", f"bridge-{uuid.uuid4().hex[:8]}")
BRIDGE_NAME = os.getenv("BRIDGE_NAME", "Luna Device Bridge")

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("device-bridge")

app = FastAPI(title="Luna Device Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
pcs = set()
cameras: Dict[str, Dict] = {} # device_id -> {config, player}

class ConnectRequest(BaseModel):
    device_id: str
    sdp: str
    type: str

class CameraConfig(BaseModel):
    device_id: str
    name: str
    rtsp_url: str
    username: Optional[str] = None
    password: Optional[str] = None

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting Luna Device Bridge: {DEVICE_ID}")
    asyncio.create_task(heartbeat_loop())

async def heartbeat_loop():
    """Register and maintain connection with Luna API."""
    client = httpx.AsyncClient()
    while True:
        try:
            # Heartbeat to Luna API
            url = f"{LUNA_API_URL}/devices/{DEVICE_ID}/heartbeat"
            headers = {"X-Device-Token": DEVICE_BRIDGE_TOKEN}
            resp = await client.post(url, headers=headers)
            
            if resp.status_code == 404:
                # Need to re-register
                logger.info("Bridge not registered, registering now...")
                reg_url = f"{LUNA_API_URL}/devices"
                # This requires a user token normally, but for now we assume 
                # the bridge is pre-registered or uses a special internal key.
                pass
            
            logger.debug(f"Heartbeat sent: {resp.status_code}")
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
        
        await asyncio.sleep(30)

@app.post("/cameras")
async def add_camera(config: CameraConfig):
    """Add a new EZVIZ or RTSP camera to the bridge."""
    cameras[config.device_id] = {
        "config": config,
        "status": "idle"
    }
    logger.info(f"Camera added: {config.name} ({config.device_id})")
    return {"status": "added", "device_id": config.device_id}

@app.post("/cameras/{device_id}/snapshot")
async def capture_snapshot(device_id: str):
    """Capture a single frame from the camera's RTSP stream."""
    if device_id not in cameras:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    config = cameras[device_id]["config"]
    rtsp_url = config.rtsp_url
    if config.username and config.password:
        from urllib.parse import urlparse
        parsed = urlparse(rtsp_url)
        rtsp_url = f"{parsed.scheme}://{config.username}:{config.password}@{parsed.netloc}{parsed.path}"

    try:
        # In a real implementation with aiortc/av, we'd open the stream, 
        # wait for a keyframe, and encode it. 
        # For this bridge, we'll use a simplified MediaPlayer approach.
        player = MediaPlayer(rtsp_url)
        
        # We need to wait a bit for the stream to open and provide a frame
        await asyncio.sleep(2.0)
        
        if not player.video:
            raise Exception("No video track found in RTSP stream")
            
        # aiortc MediaPlayer doesn't easily expose 'capture one frame' 
        # without a complex loop. In a production bridge, we'd use cv2.VideoCapture.
        # For now, let's return a placeholder or implement basic CV2 if available.
        try:
            import cv2
            import numpy as np
            
            cap = cv2.VideoCapture(rtsp_url)
            success, frame = cap.read()
            if not success:
                raise Exception("CV2 failed to read frame from RTSP")
            
            _, buffer = cv2.imencode('.jpg', frame)
            img_b64 = base64.b64encode(buffer).decode('utf-8')
            cap.release()
            
            return {
                "image_b64": img_b64,
                "timestamp": datetime.utcnow().isoformat(),
                "device_id": device_id
            }
        except ImportError:
            # Fallback to placeholder if CV2 not installed
            logger.warning("cv2 not found, returning placeholder image")
            return {
                "image_b64": "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", # 1x1 transparent
                "timestamp": datetime.utcnow().isoformat(),
                "device_id": device_id,
                "warning": "cv2 not installed on bridge"
            }
    except Exception as e:
        logger.error(f"Snapshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bridge/connect")
async def connect(request: ConnectRequest):
    """Establish WebRTC connection for a camera stream."""
    if request.device_id not in cameras:
        raise HTTPException(status_code=404, detail="Camera not found on this bridge")
    
    config = cameras[request.device_id]["config"]
    offer = RTCSessionDescription(sdp=request.sdp, type=request.type)
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            await pc.close()
            pcs.discard(pc)

    # Open RTSP stream
    try:
        # Format RTSP URL if credentials provided
        rtsp_url = config.rtsp_url
        if config.username and config.password:
            # rtsp://user:pass@ip:554/...
            from urllib.parse import urlparse
            parsed = urlparse(rtsp_url)
            rtsp_url = f"{parsed.scheme}://{config.username}:{config.password}@{parsed.netloc}{parsed.path}"
        
        player = MediaPlayer(rtsp_url)
        if player.video:
            pc.addTrack(player.video)
        
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
    except Exception as e:
        logger.error(f"Failed to connect to RTSP: {e}")
        await pc.close()
        pcs.discard(pc)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status")
async def status():
    return {
        "bridge_id": DEVICE_ID,
        "cameras": list(cameras.keys()),
        "active_connections": len(pcs)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
