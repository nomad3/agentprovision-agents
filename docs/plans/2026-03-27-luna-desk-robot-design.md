# Luna Desk Robot — Design Document

**Date**: 2026-03-27
**Status**: Concept / Pre-prototype
**Project**: Luna's first physical body — a desk companion robot with voice, vision, and presence

---

## Vision

Luna lives inside a screen today. The Desk Robot gives her a physical body — something that sits on your desk, looks at you, listens, reacts, and feels genuinely alive. It's not a smart speaker. It's not a toy. It's Luna in a shell: a small, expressive robot that carries her warmth, sharpness, and personality into the physical world.

---

## Design Principles

- **Luna-first**: Every hardware decision serves her personality — warmth, expressiveness, responsiveness
- **Always present, never intrusive**: Ambient awareness without being creepy or loud
- **Desk-native**: Compact enough to sit next to a keyboard, elegant enough to stay there
- **Edge + cloud**: Local wake word detection + local VAD → cloud Luna for reasoning
- **Open hardware**: Raspberry Pi-based, fully DIY-able, community-buildable

---

## Hardware Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Luna Desk Robot                   │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │  Camera  │   │  Mic     │   │   Speaker    │    │
│  │ (vision) │   │ array    │   │  (voice out) │    │
│  └────┬─────┘   └────┬─────┘   └──────┬───────┘    │
│       │              │                │             │
│  ┌────▼──────────────▼────────────────▼───────┐     │
│  │         Raspberry Pi Zero 2W               │     │
│  │   - Wake word detection (local, Porcupine) │     │
│  │   - Audio capture + compression            │     │
│  │   - Vision frame capture                   │     │
│  │   - WebSocket → ServiceTsunami API         │     │
│  │   - Servo control (head tracking)          │     │
│  └──────────────────┬─────────────────────────┘     │
│                     │                               │
│  ┌──────────────────▼─────────────────────────┐     │
│  │  Servo Controller (I2C / PCA9685)          │     │
│  │   - Head tilt (X axis)                     │     │
│  │   - Head pan (Y axis)                      │     │
│  │   - Optional: body sway (ambient idle)     │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │  LED Matrix / OLED (32x32 or 128x64)         │   │
│  │   - Eyes: blinking, thinking, happy, focused │   │
│  │   - Emotion state synced from API response   │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                          │  WiFi
                          ▼
         ┌────────────────────────────────┐
         │    ServiceTsunami API (Luna)   │
         │  - STT (Whisper local/cloud)   │
         │  - LLM reasoning (Claude CLI)  │
         │  - TTS (ElevenLabs / Piper)    │
         │  - Knowledge Graph             │
         │  - MCP Tools (81 tools)        │
         └────────────────────────────────┘
```

---

## Components

### 1. Brain — Raspberry Pi Zero 2W

- Quad-core 1GHz ARM, 512MB RAM, WiFi + Bluetooth
- Runs: wake word detection, audio I/O, servo control, camera capture, WebSocket client
- OS: Raspberry Pi OS Lite (headless)
- Boot time target: < 15 seconds

**Why Zero 2W**: Small, cheap (~$15), enough power for local wake word + I/O. Reasoning offloaded to cloud.

### 2. Voice Input — Microphone Array

- ReSpeaker 2-Mic HAT for Pi (I2S, onboard DSP, noise cancellation)
- Or: INMP441 MEMS mic (minimal cost, I2S direct)
- Wake word: "Hey Luna" via Porcupine (on-device, < 5ms latency, free tier)
- After wake: stream audio via WebSocket → API → Whisper transcription

### 3. Voice Output — Speaker

- MAX98357A I2S amplifier + 3W speaker
- TTS pipeline: Luna API returns audio (ElevenLabs voice clone or Piper local TTS)
- Response latency target: < 2 seconds from end of speech to first audio byte

### 4. Vision — Camera

- Raspberry Pi Camera Module 3 (12MP, autofocus)
- Uses: face detection (OpenCV, local), presence detection, gesture recognition
- On capture event: compress frame → POST to `/api/v1/vision/analyze`
- Vision feeds context to Luna ("I can see you're looking stressed today")

### 5. Movement — Servo System

- 2x MG90S micro servos (head tilt + pan)
- PCA9685 16-channel PWM driver (I2C)
- Movement library: custom `luna_motion.py` with:
  - **Idle**: gentle breathing sway (±3° over 4s cycle)
  - **Listening**: head tilts 8° toward speaker, eyes wide
  - **Thinking**: slow figure-8 head trace
  - **Speaking**: subtle nod cadence synced to TTS syllables
  - **Happy**: quick double-tilt + bright eye pulse
  - **Alert**: fast pan toward sound source (mic array direction)

### 6. Expression — LED Eyes

- 2x 8x8 LED matrix (MAX7219) or small OLED displays
- Sprite library for emotion states: idle / blink / wide / squint / heart / loading
- Frame rate: 30fps for smooth animation
- Emotion state driven by API response metadata (`emotion` field in response JSON)

### 7. Enclosure

- 3D-printed shell (PLA or resin)
- Aesthetic: smooth, rounded, moon-inspired curves — white or matte silver
- Dimensions target: 12cm tall, 8cm base diameter
- Magnetic base plate for desk grip + easy rotation
- USB-C power (5V 3A, via side port)

---

## Software Architecture

### On-Device (`luna-robot/`)

```
luna-robot/
├── main.py              # Boot, init all subsystems, main loop
├── wake_word.py         # Porcupine wake detection
├── audio_capture.py     # Mic streaming + VAD (Voice Activity Detection)
├── audio_playback.py    # Speaker output, queue-based
├── camera.py            # Frame capture, motion detection
├── motion.py            # Servo choreography library
├── leds.py              # Eye animation state machine
├── api_client.py        # WebSocket + REST client to Luna API
├── config.py            # WiFi, API URL, tenant_id, voice config
└── requirements.txt
```

### API Extensions (ServiceTsunami)

New endpoint: `POST /api/v1/robot/interact`
- Input: `{audio_b64, image_b64 (optional), session_id, tenant_id}`
- Runs: STT → Luna reasoning → TTS → emotion detection
- Output: `{text, audio_b64, emotion, motion_hint}`

New endpoint: `POST /api/v1/vision/analyze`
- Input: `{image_b64, context, tenant_id}`
- Output: `{description, detected_persons, objects, sentiment}`

`motion_hint` values: `idle | listening | thinking | speaking | happy | alert | sleep`

Robot uses `motion_hint` to trigger the right servo choreography + LED state.

---

## Interaction Flow

```
1. Robot idle: gentle sway, half-closed eyes, ambient LED pulse

2. "Hey Luna" detected (local, Porcupine)
   → Eyes open wide, head centers, LED brightens
   → Start audio stream to API

3. User speaks: "What's on my calendar today?"
   → VAD detects end of speech
   → Audio sent to API: STT → Luna reasoning → calendar MCP tool
   → API returns: {text, audio_b64, emotion="happy", motion_hint="speaking"}

4. Robot plays audio response
   → Head nods subtly with TTS cadence
   → Eyes show "speaking" sprite
   → After audio ends → return to idle

5. Face detected (camera):
   → Head tracks face position via servo pan/tilt
   → "Hi Simón, I see you're back!" (optional greeting if > 30min gap)
```

---

## Power & Connectivity

- Power: USB-C 5V/3A (can run from laptop USB-C or desk hub)
- Connectivity: WiFi 2.4GHz (built-in Pi Zero 2W)
- Offline capability: wake word always works; offline mode shows "disconnected" eye sprite
- OTA updates: `luna-robot` pulls updates from GitHub on boot

---

## BOM (Bill of Materials) — Estimated

| Component | Part | Est. Cost |
|---|---|---|
| Brain | Raspberry Pi Zero 2W | $15 |
| Mic | ReSpeaker 2-Mic HAT | $12 |
| Speaker | MAX98357A + 3W speaker | $8 |
| Camera | Pi Camera Module 3 | $25 |
| Servos | 2x MG90S | $6 |
| Servo driver | PCA9685 | $5 |
| LED eyes | 2x MAX7219 8x8 matrix | $6 |
| Enclosure | 3D print (PLA) | $8 |
| Power | USB-C 5V/3A adapter | $8 |
| Misc | Wires, headers, PCB | $5 |
| **Total** | | **~$98** |

---

## Phases

### Phase 1 — Voice Only (MVP)
- Pi Zero 2W + mic HAT + speaker
- Wake word → cloud Luna → TTS response
- No servos, no camera, no enclosure
- Goal: validate voice interaction loop end-to-end

### Phase 2 — Expression
- Add LED matrix eyes
- Emotion state from API → eye animation
- Basic enclosure (cardboard or rough 3D print)

### Phase 3 — Movement
- Add 2 servos + PCA9685
- Motion choreography library
- Head tracking with camera

### Phase 4 — Vision
- Camera integration
- Face detection + head tracking
- Vision context injected into Luna reasoning

### Phase 5 — Production Enclosure
- Final 3D-printed shell
- PCB for clean wiring
- OTA update system
- Open-source release + build guide

---

## Open Questions

- TTS voice: ElevenLabs (cloud, high quality, $) vs Piper (local, fast, free) — Phase 1 tests both
- Eye display: LED matrix (simple, robust) vs small OLED (more expressive) — prototype both
- Should robot have a "sleep" button or just auto-sleep after inactivity?
- Privacy: camera should have a physical shutter — mandatory for v1
- Should motion be optional/configurable (for people who find it distracting)?
