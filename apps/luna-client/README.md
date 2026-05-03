# apps/luna-client

Native AI client — Tauri 2 desktop (macOS ARM64) + React + Vite, with PWA fallback served over Cloudflare tunnel at `luna.agentprovision.com`. Lives in the menu bar with a global command palette, screenshot/clipboard capture, activity tracking, and a separate spatial HUD window.

For full architecture see [`../../CLAUDE.md`](../../CLAUDE.md). For iOS-specific notes see [`IOS_BUILD.md`](IOS_BUILD.md).

> **Note:** native audio push-to-talk described in older design docs (PR #154) is not currently in the tree — `cpal` is not in `src-tauri/Cargo.toml` and no `start_audio_capture`/`stop_audio_capture` functions exist. There is no native voice capture path in this app today; if a tenant wires voice in, it goes through the API's `/api/v1/media/transcribe` endpoint, not a Rust handler.

## Layout

```
src/                              # React app (Vite)
├── App.jsx                       # window-label routing (main vs spatial_hud)
├── api.js                        # axios client + JWT
├── components/
│   ├── ChatInterface.jsx
│   ├── CommandPalette.jsx        # opened by Cmd+Shift+Space
│   ├── MemoryPanel.jsx
│   ├── NotificationBell.jsx
│   ├── ActionApproval.jsx        # trust-gated local action approval
│   ├── ClipboardToast.jsx
│   ├── TrustBadge.jsx
│   ├── WorkflowSuggestions.jsx
│   ├── LoginForm.jsx
│   ├── luna/                     # avatar / emote subcomponents
│   └── spatial/                  # Three.js scenes for spatial_hud window
├── context/
│   └── AuthContext.jsx
└── hooks/
    ├── useActivityTracker.js     # window-title-based activity capture
    ├── useLunaStream.js          # SSE streaming chat
    ├── useNotifications.js
    ├── useSessionEvents.js       # /chat/sessions/{id}/events/stream
    ├── useShellPresence.js       # heartbeat to API
    └── useTrustProfile.js        # local-action trust tier
src-tauri/                        # Rust side (Tauri plugins)
├── src/main.rs                   # 5-line shim → luna_lib::run()
├── src/lib.rs                    # all Rust handlers + setup
├── tauri.conf.json
└── Cargo.toml
public/
index.html
nginx.conf                        # PWA hosting config
vite.config.js
```

## Run locally

```bash
cd apps/luna-client
npm install
npm run tauri dev                       # desktop hot reload
```

PWA-only:

```bash
npm run dev                             # Vite at http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000 npm run build
```

Type-check Rust:

```bash
cd src-tauri && cargo check
```

## Don't build releases locally

Push to `main` and let GitHub Actions build the signed macOS ARM64 DMG via [`.github/workflows/luna-client-build.yaml`](../../.github/workflows/luna-client-build.yaml). Release artifact powers the auto-updater. Local production builds aren't signed and won't ingest the auto-updater feed.

## Key integrations (in `src-tauri/src/lib.rs`)

- **Global shortcuts** (`setup_global_shortcut`, line 392)
  - `Cmd+Shift+Space` — emits `toggle-palette`; React opens the `CommandPalette`. Also un-hides the main window if needed.
  - `Cmd+Shift+L` — toggles the `spatial_hud` window's visibility.
- **System tray** (`setup_tray`, line 356) — `TrayIconBuilder` with click-to-show/focus the main window.
- **Spatial HUD** — separate Tauri window labeled `spatial_hud`. Toggled by the shortcut above; `App.jsx` routes by window label with a 1s safety fallback to `main`. The Rust `project_embeddings` command does a 3-PC projection for the Three.js scene.
- **Native handlers** exposed to React via `invoke()`: `capture_screenshot`, `haptic_feedback`, `get_active_app`, `read_clipboard`, `toggle_spatial_hud`, `start_spatial_capture`, `project_embeddings`.
- **Activity context** — `resolve_app_context`, `get_subprocess_context`, `extract_project_from_args` resolve the user's current tool/project from the active window title (Claude Code, Docker CLI, editors, etc.) for the activity tracker.
- **Auto-updater** — `tauri-plugin-updater`. Checks on startup and periodically. Emits `update-available` for the React banner.

## Required env (frontend)

```
VITE_API_BASE_URL=http://localhost:8000        # API host port
```

## iOS / Android

Blocked on Apple Developer Program ($99/yr). Free-tier team is insufficient for Tauri mobile signing. See [`IOS_BUILD.md`](IOS_BUILD.md).

## Container image

`Dockerfile` + `nginx.conf` produce the PWA hosting image used by the `luna.agentprovision.com` tunnel route. Desktop binaries come from the GitHub Actions workflow, not Docker.
