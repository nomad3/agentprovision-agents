# Luna Necklace — Design Document

**Date**: 2026-03-27
**Status**: Concept / Pre-prototype
**Project**: Luna as a wearable — always with you, always aware, always a tap away

---

## Vision

Luna's avatar wears a crescent moon necklace. That's not a coincidence — it's the seed of this idea. The Luna Necklace is a wearable AI pendant: crescent moon shape, worn around your neck, always listening in ambient mode, always connected to Luna. Push the moon to talk. Luna answers through your earbuds. It captures context throughout your day — meetings, conversations, ideas — and feeds it all back to your knowledge graph.

This is Luna's most intimate form factor. Not on your desk. On you.

---

## Design Principles

- **Ambient by default**: Not intrusive. Listens for context passively, activates explicitly on press
- **Fashion-forward**: Looks like jewelry, not a gadget. Crescent moon shape, minimal branding
- **Privacy-first**: Physical LED indicator whenever mic is active. One-press to mute. Always visible status
- **Luna-native**: Everything captured feeds into Luna's knowledge graph — not a standalone device
- **Long battery life**: 12h active minimum, 3 days standby

---

## Form Factor

```
        ╭──────╮
       ╱        ╲      ← Crescent moon pendant
      │   ● LED  │     ← Soft ambient LED (privacy indicator)
      │   [ ]    │     ← Tactile press button (center)
       ╲        ╱
        ╰──────╯
           │
      ════════════     ← Thin stainless chain (adjustable 16"-20")

Pendant dimensions: 35mm wide × 20mm tall × 8mm deep
Material: Brushed aluminum or stainless steel housing
Weight target: < 15g
```

---

## Hardware Architecture

```
┌──────────────────────────────────────────────┐
│               Luna Necklace                  │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │ MEMS Mic │  │  Button  │  │ LED Ring  │  │
│  │(ambient) │  │ (press)  │  │(privacy)  │  │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│       │             │              │         │
│  ┌────▼─────────────▼──────────────▼──────┐  │
│  │           nRF52840 (Nordic BLE SoC)   │  │
│  │  - BLE 5.0 to phone (low power)       │  │
│  │  - Local VAD (wake on voice)          │  │
│  │  - Ambient capture (on hold)          │  │
│  │  - Button FSM (tap / hold / double)   │  │
│  │  - LED control                        │  │
│  └───────────────────────────────────────┘  │
│                                              │
│  ┌───────────────────────────────────────┐   │
│  │  LiPo 200mAh + USB-C charging         │   │
│  └───────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
           │  BLE 5.0
           ▼
   ┌───────────────────┐
   │   Luna Mobile App │   (iOS / Android)
   │  - BLE relay      │
   │  - Audio buffer   │
   │  - STT → API      │
   └────────┬──────────┘
            │  HTTPS / WebSocket
            ▼
   ┌────────────────────────────────┐
   │    ServiceTsunami API (Luna)   │
   │  - STT (Whisper)               │
   │  - Reasoning (Claude CLI)      │
   │  - Knowledge graph update      │
   │  - TTS → earbuds via phone     │
   └────────────────────────────────┘
```

---

## Components

### 1. MCU — nRF52840

- Nordic Semiconductor SoC: ARM Cortex-M4F, 1MB Flash, 256KB RAM
- BLE 5.0 + NFC (optional tap-to-pair)
- Ultra-low power: 4.6μA sleep, wakes on button or VAD threshold
- Runs: Zephyr RTOS or bare-metal firmware
- SDK: nRF5 SDK or nRF Connect SDK

**Why nRF52840**: Industry standard for BLE wearables (used in AirPods, Fitbit, Tile). Best power/performance ratio for this use case.

### 2. Microphone — MEMS

- PDM MEMS mic (e.g. Knowles SPH0641LU4H-1 or ST MP34DT06J)
- Always-on in VAD (Voice Activity Detection) mode at < 50μA
- On VAD trigger or button press: full capture at 16kHz/16-bit
- Audio streamed over BLE to phone for STT processing

### 3. Interaction — Button

- Single tactile button (IP65 rated, 2mm travel)
- Interaction modes:
  - **Single tap**: Start talking to Luna (explicit invoke)
  - **Hold**: Ambient capture mode — capture conversation context (whispers to knowledge graph)
  - **Double tap**: Cancel / mute
  - **Triple tap**: Send "Hey Luna, what was that?" (summarize last 60s of ambient)

### 4. Privacy LED

- Single RGB LED (diffused through moon cutout or edge glow)
- States:
  - **Off**: idle, not recording
  - **Pulsing white**: connected, standby
  - **Solid orange**: ambient capture active (always visible to others nearby)
  - **Solid blue**: talking to Luna (explicit mode)
  - **Solid red**: muted / privacy off
  - **Breathing purple**: Luna is thinking / processing

### 5. Power

- LiPo 200mAh (fits within pendant thickness)
- Estimated battery life:
  - Standby (BLE connected): ~3 days
  - Ambient capture (6h/day): ~12h/day active use
  - Full active (talking frequently): ~6-8h
- Charging: USB-C on pendant bottom edge (magnetic pogo pins optional for v2)
- Charge time: ~45 minutes

### 6. Enclosure

- Material: CNC-machined aluminum or stainless steel
- Finish: brushed or matte (silver / gold / black variants)
- Shape: crescent moon (35mm × 20mm × 8mm)
- IP53 rating: splash resistant
- Chain: stainless steel, 2 length options (16" choker, 20" pendant)
- Clasp: standard lobster clasp + extension chain

---

## Software Architecture

### Firmware (`luna-necklace-firmware/`)

```
luna-necklace-firmware/
├── main.c               # Boot, peripheral init, main loop
├── ble.c                # BLE GATT server, audio streaming service
├── mic.c                # PDM capture, VAD, ring buffer
├── button.c             # FSM: tap/hold/double/triple detection
├── led.c                # LED state machine, breathing animations
├── power.c              # Sleep/wake management, battery ADC
└── config.h             # Firmware config (thresholds, UUIDs, etc.)
```

BLE GATT Services:
- **Luna Audio Service**: stream 16kHz PCM chunks to phone
- **Luna Command Service**: receive LED commands, mute state from phone
- **Luna Status Service**: battery %, mic state, firmware version

### Mobile App Extensions (`luna-app/`)

New to the Luna mobile app:

- **BLE Manager**: scan, pair, reconnect necklace
- **Audio Relay**: receive BLE audio → buffer → POST to `/api/v1/robot/interact`
- **TTS Relay**: receive audio from API → play through earbuds
- **Ambient Uploader**: buffer ambient captures → POST to `/api/v1/ambient/ingest`
- **Privacy controls**: UI to review/delete ambient captures before they're processed

### API Extensions (ServiceTsunami)

New endpoint: `POST /api/v1/ambient/ingest`
- Input: `{audio_b64, duration_s, captured_at, tenant_id}`
- Runs: STT → entity extraction → knowledge graph update
- Output: `{entities_created, relations_created, summary}`
- Side effect: creates memory activity logs + entities from captured context

New endpoint: `GET /api/v1/ambient/history`
- Returns: list of ambient captures with transcripts + entities extracted
- Used by: mobile app privacy review screen

---

## Interaction Flows

### Flow 1 — Explicit Talk (Single Tap)
```
1. User taps moon
2. LED turns blue, BLE audio stream opens
3. User: "Luna, add a note — call Marco about the Q2 deal"
4. Audio → phone → API → Luna processes → TTS response
5. Response plays through earbuds: "Got it, I'll remind you to call Marco"
6. LED pulses purple (thinking) → back to white (idle)
```

### Flow 2 — Ambient Capture (Hold)
```
1. User holds moon for 1s (entering a meeting)
2. LED turns solid orange
3. Necklace captures ambient audio continuously
4. Periodically buffers 30s chunks → phone → API
5. API: STT → entity extraction → knowledge graph
   ("Marco from Nomad3 mentioned Q2 budget, deadline April 15")
6. User releases hold → LED returns to white
7. Later: "Hey Luna, what did we talk about in that meeting?" → Luna knows
```

### Flow 3 — Triple Tap (Instant Replay)
```
1. Something important just happened (10 seconds ago)
2. User triple-taps
3. LED flashes blue 3x
4. Necklace sends last 60s ambient buffer to API
5. Luna transcribes + extracts key entities + summarizes
6. Response: "You just mentioned Carla is joining the sales team in May"
7. Entity created: Carla → sales team, start date May
```

---

## Privacy Architecture

Privacy is non-negotiable for a always-worn mic device.

- **LED always on when mic is active** — hardware-level, not software-controlled
- **On-device ring buffer only** — audio never leaves pendant without button trigger
- **Ambient audio deleted after 24h** if not confirmed for processing
- **Opt-in per session** — ambient mode requires explicit hold (not always-on)
- **Review before upload** — mobile app shows transcript preview, user can delete before it hits the graph
- **Local STT option** — Whisper can run on-device (iPhone Neural Engine) for full local processing
- **Physical mute switch** — optional v2 feature: hardware mic disconnect switch on chain clasp

---

## BOM (Bill of Materials) — Estimated

| Component | Part | Est. Cost |
|---|---|---|
| MCU | nRF52840 module (e.g. Seeed XIAO) | $10 |
| Microphone | PDM MEMS mic | $3 |
| LED | RGB LED + diffuser | $1 |
| Battery | LiPo 200mAh | $5 |
| Charging | USB-C charge IC (BQ25180) | $2 |
| Button | Tactile IP65 button | $1 |
| Enclosure | CNC aluminum (prototype) | $25 |
| Chain | Stainless steel chain + clasp | $5 |
| PCB | Custom 2-layer PCB (JLCPCB) | $8 |
| Misc | Connectors, passives | $3 |
| **Total (prototype)** | | **~$63** |
| **Target retail BOM (volume)** | | **~$28** |

---

## Phases

### Phase 1 — Proof of Concept
- nRF52840 dev board + MEMS mic + button
- BLE → phone → Luna API → TTS to earbuds
- No enclosure, no LED, just validate the interaction loop
- Goal: talk to Luna via necklace prototype in < 4 weeks

### Phase 2 — Form + Privacy
- LED integration + privacy indicator
- All 3 button interaction modes
- Ambient capture pipeline (hold → knowledge graph)
- Rough 3D-printed moon shell

### Phase 3 — Enclosure v1
- CNC-machined aluminum crescent moon
- USB-C charging
- IP53 sealing
- Chain integration

### Phase 4 — Mobile App
- Luna app: BLE pairing, ambient review screen, privacy controls
- OTA firmware updates via phone
- Battery / connection status widget

### Phase 5 — Production
- Full PCB design + SMT assembly quote
- FCC / CE certification path
- Retail packaging
- Pre-order / crowdfunding campaign

---

## Open Questions

- Should v1 support NFC tap-to-pair (nRF52840 has it, nearly free to add)?
- Voice in earbuds vs haptic-only response (for silent environments)?
- Should ambient capture require explicit hold every time, or can there be a "meeting mode" toggle in app?
- Gold vs silver vs black variants — which to prototype first?
- Luna app: standalone or integrated into existing ServiceTsunami mobile experience?
- Should the necklace work without a phone nearby (e.g. direct WiFi via ESP32 variant)?
