# apps/luna-client

Native AI client — Tauri 2 desktop (macOS ARM64) + React + Vite, with PWA fallback served over Cloudflare tunnel at `luna.agentprovision.com`. Lives in the menu bar, push-to-talk, spatial HUD.

For full architecture see [`../../CLAUDE.md`](../../CLAUDE.md). For iOS-specific notes see [`IOS_BUILD.md`](IOS_BUILD.md).

## Layout

```
src/                      # React app (Vite)
├── ChatInterface.jsx
├── components/           # LunaAvatar, VoiceInput, CommandPalette, ...
├── context/              # VoiceProvider (shared useVoice instance)
├── hooks/                # useVoice (WAV-encoded PTT), useAuth, ...
└── App.jsx               # window-label routing (main vs spatial_hud)
src-tauri/                # Rust side (Tauri plugins, audio, tray, updater)
├── src/lib.rs            # cpal audio capture (start/stop_audio_capture)
├── src/main.rs           # window setup, global shortcut registration
├── tauri.conf.json
└── Cargo.toml
public/
index.html
nginx.conf                # PWA hosting config
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

## Key integrations

- **Native push-to-talk** — Rust `cpal` captures Float32 PCM in a spawned thread. The stream is `!Send` on macOS; **build and drop it on the same thread**. Frontend `useVoice` hook wraps the buffer in a proper WAV (RIFF / PCM16) header before posting to `/api/v1/media/transcribe`.
- **VoiceProvider context** — wraps the authenticated app so `VoiceInput` (chat) and `CommandPalette` share **one** `useVoice` instance. Two would register duplicate `audio-chunk` listeners.
- **Global shortcuts** — `Cmd+Shift+Space` PTT, `Cmd+Shift+L` toggles the Spatial HUD. Registered in `src-tauri/src/main.rs`. Unregister on window destroy.
- **System tray** — Open / Voice / Toggle Spatial HUD / Quit (`PredefinedMenuItem::separator` for the dividers).
- **Auto-updater** — `tauri-plugin-updater`. Checks on startup + every 30 min. Emits `update-available` → React banner.
- **Spatial HUD** — separate Tauri window label `spatial_hud`. `App.jsx` routes by label with a 1s safety fallback to `main`. Three.js knowledge nebula + A2A combat visuals + MediaPipe hand tracking.

## Required env (frontend)

```
VITE_API_BASE_URL=http://localhost:8000        # API host port
```

## iOS / Android

Blocked on Apple Developer Program ($99/yr). Free-tier team is insufficient for Tauri mobile signing. See `IOS_BUILD.md`.

## Container image

`Dockerfile` + `nginx.conf` produce the PWA hosting image used by the `luna.agentprovision.com` tunnel route. Desktop binaries come from the GitHub Actions workflow, not Docker.
