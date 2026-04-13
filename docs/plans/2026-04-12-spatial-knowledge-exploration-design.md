# Luna OS: Spatial Workstation & Workflow HUD

**Date:** 2026-04-12
**Author:** Gemini CLI
**Status:** Approved (Luna Native)
**Timeline:** 2-3 weeks
**Target:** High-productivity "Video Game" interface for AI orchestration

---

## 1. Objective

Transform the Luna Tauri app into **Luna OS**—a native, spatial operating system where Luna's memory and workflows are managed through a high-performance HUD. The goal is to move beyond "Chat" into a "Command and Control" paradigm optimized for speed, visual clarity, and native OS integration.

- **(A) The HUD (Heads-Up Display)**: Transparent, always-on-top interface elements showing real-time system stats (Tokens, Costs, Active Agents).
- **(B) Mission Control**: Visual orchestration of Temporal workflows as "Active Quests" with real-time status bars.
- **(C) Spatial Nebula**: 3D Knowledge Graph navigation using **WASD + Mouse/Gestures**, mimicking a space-flight simulator or open-world game.

---

## 2. Interaction Paradigm: The "Gamer" Workflow

To maximize productivity, Luna OS adopts a keyboard-first, low-latency layout inspired by competitive gaming:

- **WASD / Space / Ctrl**: Fly through the Memory Nebula.
- **`1`, `2`, `3`, `4`**: Hot-swap between active Agent Coalitions (the "Party").
- **`Tab`**: Open/Close the **Minimap** (High-level cluster view of the Knowledge Graph).
- **`E` (Interact)**: Inspect a node (entity/observation) to open its detail panel.
- **`R` (Reload/Refresh)**: Force a re-index of the current context.
- **`Cmd + Shift + L`**: Toggle Luna OS HUD visibility.

---

## 3. Native OS Integration (Tauri + Rust)

### 3.1. System-Level "God Mode"
- **Window Management**: Use Tauri's native window API to create "Floating Portals"—small, transparent widgets that stick to specific areas of the screen.
- **Global Event Hook**: Capture system-wide keyboard shortcuts even when Luna is not focused.
- **Performance**: Move the UMAP (768D → 3D) projection and D3-force physics to a dedicated Rust thread (`tokio`) to maintain 144fps rendering.

### 3.2. Resource HUD (Real-Time)
A top-screen overlay showing:
- **Token Bandwidth**: Current usage vs. rate limits.
- **Compute Heat**: Real-time cost of the active session in USD.
- **Agent Party**: Avatars of the 4 agents in the current `CoalitionWorkflow`, pulsing when they are "thinking."

---

## 4. Visual Layout (The "Game" View)

### 4.1. The Nebula (Main Canvas)
A 3D star-field where:
- **Entities** = Major Stars.
- **Observations** = Orbiting Planets.
- **Relationships** = Gravity Wells/Lines.
- **Workflows & A2A Comms** = Flowing data-beams connecting nodes. When Agent A communicates with Agent B, a high-velocity pulse travels between their avatars or the nodes they are currently "mining."

### 4.2. The Quest Log & A2A HUD (Workflow Orchestration)
A side-aligned list of active Temporal workflows and A2A sessions:
- **Progress Bars**: Real-time % completion of the `CoalitionWorkflow`.
- **A2A Comms Feed**: A scrolling "Combat Log" style terminal showing internal agent-to-agent negotiations (Blackboard entries before they are finalized).
- **Consensus Meter**: A "Boss Health Bar" style visualization showing how close the agents are to reaching consensus (0-100%).

### 4.3. The Shared Blackboard (Team Inventory)
Visualized as a central "Relic" or floating "Shared Inventory" panel:
- **Entries**: Each `BlackboardEntry` appears as a new "Loot" item added to the session.
- **Versioning**: Using `board_version` to show the "Evolution" of the solution as agents refine each other's work.
- **Author Scoping**: Color-coded by the `author_slug` to instantly identify which agent contributed which piece of evidence.

---

## 5. Implementation Phases (Enhanced for A2A)

### Phase 1: The OS Scaffolding
- [ ] Implement the **Transparent HUD** container in Tauri.
- [ ] Add the **Keyboard Controller** (WASD + Global Hotkeys).
- [ ] Create the **Token/Cost HUD** widget wired to the API.

### Phase 2: Tactical Nebula & A2A Visuals
- [ ] Build the 3D renderer using `react-three-fiber`.
- [ ] Implement **Agent Avatars** that physically move to the nodes they are analyzing.
- [ ] Add **Comms Beams**: Visual pulses that fire between agents when `publish_event` triggers a Redis message.

### Phase 3: Workflow HUD (The Mission Log)
- [ ] Wire the **Collaboration SSE Stream** to visual progress bars and the "A2A Combat Log."
- [ ] Implement **Consensus Shaders**: The screen edges glow "Gold" when consensus is reached, or "Red" when a conflict/contradiction is detected.
- [ ] Add the **Shared Blackboard Panel**: A keyboard-accessible UI (`Tab`) to browse the evolving state of the `CollaborationSession`.

---

## 6. Success Criteria

1. **Flow State**: User can navigate 5,000+ nodes using WASD without taking hands off the keyboard.
2. **Ambient Awareness**: User knows the exact status and cost of a complex workflow just by glancing at the HUD while working in another app.
3. **Physicality**: Manipulating memory feels tactile, fast, and responsive—more like a modern game engine than a web form.

---

## 3. Native Architecture (Tauri)

### 3.1. Tech Stack

- **Frontend**: React + `react-three-fiber` (rendering inside a transparent Tauri window).
- **Backend (Rust)**: 
    - `umap-rs`: For 768D → 3D vector projection.
    - `opencv` or `media-pipe-rs`: For native camera access and gesture recognition.
    - `enigo`: For simulating native mouse/keyboard events based on gestures.
- **Transport**: Tauri Commands (IPC) instead of REST/SSE where possible for lower latency.

### 3.2. Data Flow (Native)

```
Postgres (PGVector) → API: GraphExportService
                          │
                          ▼
Luna App (Tauri Rust Backend) ───► Native Camera (High FPS)
    │           │                      │
    │           ├─ umap-rs (Compute) ◄─┘
    │           └─ Gesture Engine ─────┐
    │                                  │
    ▼                                  ▼
Tauri Webview (React + 3D) ◄──── IPC Events (Pinch, Zoom, Select)
    │
    └─ Transparent HUD Layer (60fps)
```

---

## 4. Native Interaction Mapping

| Gesture | Logic | Native OS Action |
|---------|------------|---------------------|
| **Pinch & Move** | Index + Thumb | Manipulate 3D nodes in the HUD |
| **Two-Hand Spread**| Distance increase | Zoom graph; Increase window transparency |
| **"Throw" to Edge**| Flick movement | Archive node; Minimize HUD to System Tray |
| **Palm Open (Wait)**| 2-second hold | Toggle "System Transparency" (see through the graph) |
| **Point & Click** | Finger tap | Focus the node and copy metadata to OS Clipboard |

---

## 5. Implementation Phases

### Phase 1: The Transparent Window
- [ ] Configure `tauri.conf.json` for multi-window support.
- [ ] Create `spatial_hud` window with `transparent: true` and `decorations: false`.
- [ ] Implement Rust-side window shadowing and "click-through" logic (`set_ignore_cursor_events`).

### Phase 2: Rust UMAP Engine
- [ ] Integrate `umap-rs` into the Tauri backend.
- [ ] Create a Tauri command `get_spatial_data` that fetches embeddings from the API and projects them in a background Rust thread.
- [ ] Implement caching for 3D coordinates on the local machine for instant loading.

### Phase 3: Native Gesture Processing
- [ ] Implement a Rust-based webcam listener.
- [ ] Integrate a lightweight gesture model (e.g., a port of MediaPipe or a custom ONNX model) to run natively.
- [ ] Stream gesture events (X, Y, Z + GestureType) to the frontend via Tauri's `emit` system.

---

## 6. Success Criteria (Native)

1. **System Integration**: The HUD feels like a part of the OS, not a website.
2. **Zero-Latency**: Gestures feel "magnetic" with no visible lag between hand movement and 3D response.
3. **Hardware Efficiency**: Native Rust processing keeps CPU usage low despite complex 3D and UMAP compute.
4. **Multitasking**: User can interact with the graph while simultaneously using other professional tools.
