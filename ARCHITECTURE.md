# Home Theater Manager — Architecture

> A self-hosted "movie theater" for a home cinema: schedule showings, build
> trailer+feature playlists, play them to a projector over SDI with HDMI audio,
> and print novelty tickets on an Epson thermal printer.

This document is the design of record. Code should follow it; if reality forces a
change, update this doc in the same PR.

---

## 0. Implementation Status

| Area | Status |
|---|---|
| Management plane (web UI, API, DB, scheduler, ticketing) | **Implemented (Phase 1)** |
| Settings tab: video/audio output routing | **Implemented (Phase 1)** |
| Rich media probe (aspect, audio profile, size, bitrate) | **Implemented (Phase 1)** |
| Playback service (control API + mock mode) | **Implemented (Phase 1)** |
| Additive schema migrations (run on startup) | **Implemented** |
| PDF tickets (80mm receipt + 8.5×11 color) | **Implemented (Phase 1)** |
| CLI installer for Ubuntu / Rocky (`deploy/install.sh`) | **Implemented** |
| Hardware auto-discovery (NVIDIA/AMD/Intel + iGPU, DeckLink, printer, audio) | **Implemented** |
| Blackmagic DeckLink driver installer (DKMS) | **Implemented** |
| `htm` management CLI (re-discover, reconfigure, logs, update) | **Implemented** |
| ffmpeg playback runner (selected outputs + idle screen) | **Implemented; hardware validation pending** |
| Real host playback service packaging (systemd + device permissions) | Designed, not built (Phase 3) |
| HDR10 SDI signaling | Designed (Phase 4) |

### Repository layout
```
backend/        FastAPI app: routers/ (media, showings, tickets, playback,
                settings), services/ (media_scan, scheduler, showings,
                ticketing[PDF], playback_client, settings_store),
                migrations.py, models.py, schemas.py, config.py, database.py
frontend/       React + Vite SPA (tabs/ + components/), Caddy (TLS :443 + /api)
playback-mock/  FastAPI playback service (§6): mock mode by default, ffmpeg via
                HTM_PLAYBACK_DRIVER=ffmpeg
deploy/         install.sh (curl|bash installer), discover.sh (hardware probe),
                install-decklink.sh (Blackmagic DKMS driver),
                htm-menu.sh (management CLI, installed as `htm`)
runtime/        hardware discovery output (gitignored), mounted at /runtime
docker-compose.yml, .env.example
```

---

## 1. Goals & Non-Goals

### Goals
- Single standalone server with an NVIDIA GPU and a Blackmagic DeckLink card.
- Headless host: **no desktop GUI**. All operation is via a web UI on port **443**.
- Play scheduled movies + trailers to a projector via **SDI** (DeckLink), audio via **HDMI**.
- **HDR10 (static metadata)** output over SDI. (See §8 — HDR10+ is best-effort/stretch.)
- Web UI with four tabs: **Schedule**, **Media**, **Now Showing**, **Ticketing**.
- "New Showing" wizard: pick showtime → pick feature file → compute runtime →
  add trailers → generate tickets.
- Media sourced from a remote server over **NFS/SMB** (mounted), or local storage.
- **PDF ticket generation** (80mm thermal receipt **or** 8.5×11 color), printed
  from the operator's workstation to any reachable printer: seat selector
  (1A–6F), name field, drink / popcorn / candy checkboxes. Unlimited reprints.
- Manual transport controls (shuttle): **Start Show / Play / Pause / End Show**.

### Non-Goals (v1)
- Multi-screen / multi-auditorium.
- User accounts beyond a single shared admin login.
- DRM / commercial content protection.
- Dolby Vision, Dolby Atmos bitstreaming.
- Mobile-native apps (responsive web only).

---

## 2. System Overview

The system is split into a **management plane** (containerized) and a
**playback plane** (runs in mock mode for demos, or on the host with direct
hardware access for ffmpeg mode). This split is
deliberate: the DeckLink kernel driver, GPU access, and frame-accurate realtime
playback are brittle inside containers, while the web/API/DB are portable and
benefit from Docker.

```
┌───────────────────────────────────────────────────────────────────────┐
│ HOST (bare metal: NVIDIA GPU + DeckLink + Desktop Video driver)         │
│                                                                         │
│  ┌──────────────────────────┐        ┌──────────────────────────────┐  │
│  │  Docker Compose          │        │  Playback Service (systemd)  │  │
│  │  (management plane)       │        │  (playback plane)            │  │
│  │                          │  HTTP  │                              │  │
│  │  ┌────────────────────┐  │  /unix │  ┌────────────────────────┐  │  │
│  │  │ reverse proxy      │  │ socket │  │ control API (FastAPI)  │  │  │
│  │  │ (Caddy) :443 TLS   │  │ ◄────► │  │  - load playlist       │  │  │
│  │  └─────────┬──────────┘  │        │  │  - play/pause/stop     │  │  │
│  │            │             │        │  │  - report state        │  │  │
│  │  ┌─────────▼──────────┐  │        │  └───────────┬────────────┘  │  │
│  │  │ frontend (React)   │  │        │              │               │  │
│  │  └────────────────────┘  │        │  ┌───────────▼────────────┐  │  │
│  │  ┌────────────────────┐  │        │  │ ffmpeg                 │  │  │
│  │  │ backend API        │  │        │  │  NVDEC decode →        │  │  │
│  │  │ (FastAPI)          │  │        │  │  decklink output muxer │  │  │
│  │  │  - scheduler       │  │        │  └───────────┬────────────┘  │  │
│  │  │  - media scan      │  │        │              │               │  │
│  │  │  - tickets/ESC-POS │  │        └──────────────┼───────────────┘  │
│  │  └─────────┬──────────┘  │                       │                  │
│  │  ┌─────────▼──────────┐  │              ┌────────▼────────┐         │
│  │  │ SQLite (volume)    │  │              │ DeckLink card   │──► SDI ──► Projector
│  │  └────────────────────┘  │              │ (+ embedded or  │         │
│  └──────────────────────────┘              │  HDMI audio)    │──► HDMI ─► AV receiver
│                                            └─────────────────┘         │
│  Mounted media: /mnt/media  (NFS/SMB from remote server over 10GbE)     │
│  USB/Network: Epson thermal printer                                     │
└───────────────────────────────────────────────────────────────────────┘
```

### Why this split
- **DeckLink** needs the host's *Desktop Video* kernel driver; matching driver
  versions across a container boundary is fragile.
- **Realtime playback** wants direct GPU + low-latency scheduling.
- Everything else (UI, scheduling logic, DB, printing) is portable and rebuildable.
- The two planes communicate over a small, well-defined **control API** (§6),
  so the management plane never touches hardware directly.

---

## 3. Components

### 3.1 Reverse proxy — Caddy
- Terminates **TLS on :443** (self-signed by default; user can drop in a real cert).
- Serves the built frontend and proxies `/api/*` to the backend.
- Single public surface. No other ports exposed externally.

### 3.2 Frontend — React + Vite (SPA)
Five tabs:
1. **Schedule** — week view (Mon–Sun columns) of all showings. Top-right
   **"New Showing"** button launches the wizard. Click a showing to edit/modify.
2. **Media** — browse mounted media; tag files as **trailer** or **feature**;
   shows probed duration, resolution, aspect ratio, codec, HDR, audio format
   (Atmos/DTS:X/PCM/…), file size, and bitrate.
3. **Now Showing** — current/next-up showing with live playback state and the
   **shuttle controls** (Start Show / Play / Pause / End Show).
4. **Ticketing** — pick a showing, choose seats (1A–6F), enter a name,
   tick drink/popcorn/candy, print. Unlimited reprints.
5. **Settings** — assign playback to video outputs (DeckLink SDI, GPU HDMI/DP,
   or several at once to mirror) and choose the audio output + mode
   (passthrough/PCM). Devices are discovered from the playback service.

The **New Showing** wizard surfaces full movie info for the chosen feature
(aspect ratio, resolution, audio profile, runtime, file size, bitrate) so the
operator can confirm the right file before scheduling.

### 3.3 Backend API — FastAPI (Python)
- REST API under `/api`.
- **Scheduler** (APScheduler): fires at each showtime to tell the playback
  service to load and start the showing's playlist.
- **Media service**: scans `/mnt/media`, runs `ffprobe` for duration/codec/HDR,
  persists metadata.
- **Ticketing service**: renders ESC/POS and sends to the Epson printer.
- **Playback client**: thin client to the host playback control API (§6).

### 3.4 Playback service — Python control API + ffmpeg runner
- Exposes the **control API** over a Unix socket (or localhost-only TCP).
- Defaults to mock mode for demos/tests. With `HTM_PLAYBACK_DRIVER=ffmpeg`, owns
  the DeckLink + GPU/audio devices and runs `ffmpeg` for active playback and the
  idle screen.
- Maintains a single playback state machine (§6.3) and reports it upstream.

### 3.5 Database — SQLite + additive migrations
- Single-file DB on a Docker volume. Sufficient for one server. Schema is written
  to be Postgres-portable (no SQLite-only features in app logic).
- **Migrations** (`backend/app/migrations.py`) run on startup: `create_all` for
  new tables plus additive `ALTER TABLE ... ADD COLUMN` for any columns the
  models gained. Idempotent and safe to re-run, so upgrades pick up new fields
  without resetting the volume. Destructive/data migrations would graduate to
  Alembic (Phase 2).

### 3.6 Tickets — server-generated PDF, client-printed
- The server **generates a PDF** (`reportlab`) in one of two styles — an 80mm
  thermal receipt or a full-page 8.5×11 color "movie ticket" — via
  `GET /api/tickets/{id}/pdf?style=receipt|fullpage`.
- The **operator's workstation prints it** to whatever printer it can reach
  (network, USB, thermal, or a normal color printer). The server has **no
  printer driver** and no direct printer connection — its only outputs are the
  projector (SDI) and audio. This matches the deployment reality: the management
  machine (browser) is where printers live.
- Tickets are still recorded in the DB (seat, name, extras, copy index) so
  reprints are tracked.

---

## 4. Media Handling

- **Mounting, not streaming.** Remote media is mounted on the host
  (`/mnt/media`, NFS or SMB) and bind-mounted read-only into the relevant
  containers/services. Over 10GbE this behaves like local disk and preserves
  seeking — essential for probing and HDR.
- SFTP-as-transport for playback is explicitly avoided (poor seek/probe behavior);
  it may be offered later only as a *copy-to-local* import.
- **Probing.** `ffprobe` extracts duration (seconds, float), container, video
  codec, resolution, frame rate, color primaries/transfer (to detect HDR10), and
  audio streams.
- **Runtime rounding.** Ticket/schedule runtime = `round(total_seconds / 60)`
  minutes (nearest minute), where total = sum of selected trailers + feature.

---

## 5. Data Model (initial)

```
MediaFile
  id, path, kind {trailer|feature}, title,
  duration_seconds (float), width, height, fps, aspect_ratio,
  video_codec, color_primaries, transfer_characteristics, is_hdr10 (bool),
  file_size (bytes), bitrate (bits/s),
  audio_codec, audio_profile, audio_channels, audio_channel_layout,
  audio_format (e.g. "Dolby Atmos (TrueHD)" / "DTS:X" / "PCM 5.1"),
  audio_summary (all tracks), scanned_at

AppSettings            # singleton (id=1): output routing
  video_output_ids (JSON list — multiple = mirror to all),
  audio_output_id, audio_mode {passthrough|pcm},
  idle_screen_mode {black|logo}, idle_logo_path,
  idle_logo_scale {fit|fill}, updated_at

Showing
  id, title, feature_id → MediaFile,
  scheduled_start (datetime), status {scheduled|playing|paused|done|canceled},
  computed_runtime_min (int), created_at, updated_at

ShowingItem            # ordered playlist entries for a showing
  id, showing_id → Showing, media_id → MediaFile,
  position (int), role {trailer|feature}

Ticket
  id, showing_id → Showing, seat (e.g. "3C" | null), name (str | null),
  incl_drink (bool), incl_popcorn (bool), incl_candy (bool),
  printed_at, copy_index

PlaybackState          # singleton, mirrors playback service
  showing_id | null, state, position_seconds, current_item_id, updated_at
```

Seat model: rows **A–F**, numbers **1–6** → `1A … 6F` (configurable extent).

---

## 6. Control API (management plane ↔ playback plane)

Small JSON API the playback service exposes; the backend is the only client.

### 6.1 Endpoints
```
POST /playback/load     { showing_id, items: [{path, role, position}],
                          outputs: { video_outputs: [id...],
                                     audio_output: id, audio_mode,
                                     idle_screen: {
                                       mode: "black"|"logo",
                                       logo_path: string|null,
                                       scale: "fit"|"fill" } } }
POST /playback/configure { outputs }   # apply output + idle screen without loading
POST /playback/start
POST /playback/pause
POST /playback/resume
POST /playback/stop      # "End Show"
GET  /playback/state     -> { state, showing_id, position_seconds, current_item }
GET  /outputs            -> { video: [{id,name,type}], audio: [{id,name,type}] }
```

Output routing comes from `AppSettings` (the Settings tab) and is passed to the
playback service on every `load`. Selecting multiple video outputs mirrors the
feed (e.g. DeckLink SDI **and** a GPU HDMI output). The playback service
enumerates available outputs via `GET /outputs` (DeckLink SDK + GPU in Phase 3;
a fixed list in the mock).

The Settings tab also uploads a single operator-supplied idle logo still. The
backend validates it as exactly **3840x2160** and stores it under `/runtime`.
When no trailer or feature is active, the playback service keeps ownership of
the selected video outputs and renders either black or the logo. `scale=fit`
preserves the whole image inside the current output raster; `scale=fill` covers
the raster and crops if needed. If logo mode is selected but no logo exists, the
backend sends black as the effective idle screen.

#### Console vs. video output routing (host level)

Distinct from *playback* output selection above is the host's **Linux console**.
Because this is a server OS, an operator may plug a monitor + keyboard into the
box for local admin, and the text console must not collide with the projector
feed. Two cases:

- **DeckLink SDI playback** bypasses the GPU framebuffer entirely, so every GPU
  connector stays free for the VGA console — no host config needed.
- **A GPU HDMI/DP connector drives the projector.** That connector is disabled
  from the kernel framebuffer console (`video=<conn>:d`) so `fbcon`/`getty` only
  ever appear on the designated console output (e.g. onboard VGA). A serial
  console (`console=ttyS0,115200`) can be added as a headless fallback.

`deploy/console-routing.sh` enumerates DRM connectors (`/sys/class/drm`) and
serial UARTs — also recorded in `runtime/hardware.json` (`connectors`, `serial`)
by `discover.sh` — and writes the kernel command line via a GRUB drop-in
(`/etc/default/grub.d/99-htm-console.cfg` on Debian/Ubuntu) or a managed
`GRUB_CMDLINE_LINUX` block + `grubby` on RHEL/Rocky. It previews by default and
only mutates GRUB with `--apply`; `sudo htm` exposes it interactively.

On `--apply` it also writes the reserved connectors to `runtime/console.json`.
`GET /api/settings/outputs` reads that file and annotates any playback video
output whose connector matches (`reserved`, `reserved_reason`); the Settings tab
badges it *console-reserved* and warns on selection. The match is by connector
*family* (HDMI/DP/VGA) because pre-Phase-3 the mock output IDs are not yet 1:1
with DRM connector names — hence **advisory (warn), not a hard block**. When the
Phase 3 playback service enumerates GPU outputs via DRM, output IDs become the
connector names and this collapses to an exact, enforceable match.

### 6.2 Shuttle button mapping (Now Showing tab)
- **Start Show** → `load` (if needed) + `start`
- **Play / Pause** → `resume` / `pause`
- **End Show** → `stop`

### 6.3 Playback state machine
```
IDLE ──load──► LOADED ──start──► PLAYING ⇄ (pause/resume) ⇄ PAUSED
   ▲                                  │
   └──────────────── stop ◄───────────┘  (also: PLAYING ──playlist end──► IDLE)
```

### 6.4 Scheduled trigger
At `Showing.scheduled_start`, the backend scheduler calls `load` then `start`
on the playback service. Manual shuttle controls can override at any time.

---

## 7. Playback Pipeline (ffmpeg + DeckLink)

- **Decode (multi-vendor):** chosen from the discovered GPU —
  **NVIDIA** NVDEC (`-hwaccel cuda`), **AMD** VAAPI (`-hwaccel vaapi` via
  `/dev/dri`, optionally ROCm), **Intel** QSV/VAAPI (integrated GPUs). The
  installer's `discover.sh` records the primary vendor + hwaccel hint; the
  Phase 3 service uses it (and can still enumerate at runtime). Software decode
  is the fallback when no supported GPU is present.
- **Output:** selected Settings targets become ffmpeg output groups. DeckLink
  defaults to `-f decklink "<device name>"`; GPU/audio targets can be supplied
  by `HTM_VIDEO_OUTPUTS_JSON` / `HTM_AUDIO_OUTPUTS_JSON` with exact `ffmpeg_args`.
- **Idle takeover:** outside active playback, the service keeps a low-cost
  ffmpeg process attached to the selected video outputs so the projector never
  falls back to a desktop/console/signal-loss state. Black uses `color=black`;
  logo mode uses the uploaded still with `scale`/`pad` for fit or `scale`/`crop`
  for fill, normalized to the active output mode.
- **Playlist:** trailers then feature, played as sequential ffmpeg invocations
  managed by the service. This keeps per-item state and pause/resume simple;
  transition smoothness remains a hardware validation point.
- **HDR10 signaling:** pass mastering-display / color metadata so the DeckLink
  emits HDR10 static metadata over SDI (see §8).
- **Audio:** embedded SDI audio is the default/cleanest path. If HDMI audio to an
  AV receiver is required, that becomes a second output and needs an explicit
  shared clock / sync strategy (flagged as a risk — §10).

---

## 8. HDR Strategy (v1 = HDR10 static)

- **Target:** HDR10 with **static** metadata (SMPTE ST 2086 mastering display +
  MaxCLL/MaxFALL), signaled over SDI on HDR-capable DeckLink cards.
- **HDR10+ (dynamic):** out of scope for v1. Dynamic per-scene metadata over SDI
  is poorly supported in practice; revisit only with confirmed card + projector
  support, and likely over HDMI rather than SDI.
- **Validation step (pre-build):** confirm exact DeckLink model supports HDR
  signaling and that the projector ingests HDR10 over SDI. Capture findings here.

---

## 9. Deployment

### 9.0 Supported OS & installer
- Target OSes: **Ubuntu Server 22.04/24.04** and **Rocky Linux 9/10** (and their
  Debian/RHEL/Alma families).
- **`deploy/install.sh`** is a `curl … | sudo bash` installer that:
  1. detects the distro (apt vs dnf) from `/etc/os-release`,
  2. installs Docker Engine + Compose plugin, `pciutils`, `usbutils`,
  3. clones the repo to `/opt/home-theater-manager`,
  4. runs **`discover.sh`** to auto-detect hardware (GPUs incl. integrated,
     DeckLink, USB thermal printers, audio) → `runtime/hardware.json` + hints,
  5. installs the **`htm`** management command,
  6. runs a **CLI wizard** (theater name, media path, seat grid, default
     ticket style) — reading from `/dev/tty` so it works through a curl pipe,
  7. writes `.env` and runs `docker compose up -d --build`.
- Non-interactive mode (`--non-interactive` + env vars) is supported for automation.
  `--no-tui` is still accepted as a backwards-compatible alias.

### 9.0.1 `htm` management CLI (`deploy/htm-menu.sh`)
Re-runnable any time (`sudo htm`): **re-discover hardware** (after swapping a
GPU/DeckLink/printer), set default ticket style, view status/logs, start/stop/
restart, and update (git pull + rebuild). Discovery results feed the Settings
tab's "Detected hardware" panel via `/runtime/hardware.json`.

### 9.0.2 Multi-vendor GPU passthrough (Phase 3 playback)
- **NVIDIA:** NVIDIA Container Toolkit + `--gpus all` (or compose `deploy.resources`).
- **AMD / Intel (incl. integrated):** pass `/dev/dri` for VAAPI; AMD ROCm adds
  `/dev/kfd`. The discovered `HTM_HWACCEL` hint selects the ffmpeg decode path.

### 9.0.3 DeckLink driver install (`deploy/install-decklink.sh`)
The installer runs when discovery finds a DeckLink but no loaded driver (CLI
prompts; also in `htm` and runnable standalone). It acquires the Desktop Video
package by trying, in order:
1. an explicit `HTM_DECKLINK_SRC` (local file, LAN URL, or signed `?verify=...` link),
2. `HTM_DECKLINK_DOWNLOAD_UUID` (opt-in best-effort against Blackmagic's gated API),
3. **Blackmagic's CDN path for a pinned version** (`HTM_DECKLINK_VERSION`, default
   16.0): `https://swr.cloud.blackmagicdesign.com/DesktopVideo/v<VER>/Blackmagic_Desktop_Video_Linux_<VER>.tar.gz`.

Blackmagic's CDN may enforce a **time-limited signed token**; when the tokenless
path is refused the script skips with clear instructions to paste a signed link.
It then installs DKMS + kernel headers, installs the core (non-GUI)
`desktopvideo` package for the distro/arch, builds the kernel module, loads it,
and verifies `/dev/blackmagic*`. A reboot may be required to build against the
running kernel.

### 9.1 Host prerequisites for Phase 3 (real playback)
- GPU driver: NVIDIA driver + Container Toolkit, **or** AMD/Intel VAAPI via
  `/dev/dri` (AMD ROCm adds `/dev/kfd`). Selected per discovered `HTM_HWACCEL`.
- Blackmagic **Desktop Video** driver — installable via `install-decklink.sh`.
- NFS/SMB mount of remote media at `/mnt/media`.
- A printer reachable from the operator's workstation (tickets are client-printed PDFs).

### 9.2 Docker Compose (management plane)
- `caddy` (:443), `frontend` (build artifact), `backend` (FastAPI),
  volume for SQLite, bind-mount `/mnt/media:ro`.
- Backend reaches the host playback service via the Unix socket / `host.docker.internal`.

### 9.3 Playback service (host)
- The same FastAPI service runs in mock mode by default. For host playback, set
  `HTM_PLAYBACK_DRIVER=ffmpeg`, provide exact device targets when defaults are
  not enough, and run it with access to `/dev/blackmagic*`, the GPU/audio
  devices, `/mnt/media`, and `/runtime` for idle-logo assets.
- Phase 3 packaging still needs a dedicated **systemd** unit with device
  permissions and restart-on-failure.

---

## 10. Risks & Open Questions

1. **Split A/V (SDI video + HDMI audio) sync.** Two interfaces = two clocks =
   lip-sync drift risk. Preference: embed audio in SDI. Decision needed if an AV
   receiver mandates HDMI audio.
2. **DeckLink HDR capability** depends on exact model; confirm before relying on
   HDR10 over SDI.
3. **ffmpeg decklink output** timing/format-switching between playlist items
   (resolution/fps changes between trailers and feature) needs hardware testing;
   may require normalizing all items to a fixed output format.
4. **Frame-accurate transport** (pause/seek to SDI) fidelity via ffmpeg TBD; a
   custom DeckLink SDK app is the fallback if ffmpeg is insufficient.
5. **Projector SDI HDR ingest** must be confirmed.

---

## 11. Phased Plan

- **Phase 0 — Design (this doc).** ✅
- **Phase 1 — Management plane:** FastAPI + React + SQLite + Caddy in Compose;
  all four tabs functional against a **mock** playback service; ffprobe-based
  media scan; ticket ESC/POS rendering (print to file/mock). ✅ **Done**
  (also: New Showing wizard, APScheduler triggers, runtime rounding, and the
  `deploy/install.sh` installer landed alongside Phase 1.)
- **Phase 2 — Hardening:** Alembic migrations, auth (single shared login),
  per-item playlist reordering UI, richer schedule conflict checks.
- **Phase 3 — Real playback service:** ffmpeg runner is wired; finish host
  systemd packaging, device permissions, and on-hardware DeckLink/GPU validation.
- **Phase 4 — HDR10 signaling + printer hardware + sync validation.**

Each phase is independently demoable; the mock playback service in Phase 1 lets
the entire UI be exercised before any hardware integration.
