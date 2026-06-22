# Home Theater Manager — Architecture

> A self-hosted "movie theater" for a home cinema: schedule showings, build
> trailer+feature playlists, play them to a projector over SDI with HDMI audio,
> and print novelty tickets on an Epson thermal printer.

This document is the design of record. Code should follow it; if reality forces a
change, update this doc in the same PR.

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
- Thermal ticket printing (Epson ESC/POS): seat selector (1A–6F), name field,
  and drink / popcorn / candy checkboxes. Unlimited reprints.
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
**playback plane** (runs on the host with direct hardware access). This split is
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
Four tabs:
1. **Schedule** — week view (Mon–Sun columns) of all showings. Top-right
   **"New Showing"** button launches the wizard. Click a showing to edit/modify.
2. **Media** — browse mounted media; tag files as **trailer** or **feature**;
   shows probed duration, resolution, codec, HDR flags.
3. **Now Showing** — current/next-up showing with live playback state and the
   **shuttle controls** (Start Show / Play / Pause / End Show).
4. **Ticketing** — pick a showing, choose seats (1A–6F), enter a name,
   tick drink/popcorn/candy, print. Unlimited reprints.

### 3.3 Backend API — FastAPI (Python)
- REST API under `/api`.
- **Scheduler** (APScheduler): fires at each showtime to tell the playback
  service to load and start the showing's playlist.
- **Media service**: scans `/mnt/media`, runs `ffprobe` for duration/codec/HDR,
  persists metadata.
- **Ticketing service**: renders ESC/POS and sends to the Epson printer.
- **Playback client**: thin client to the host playback control API (§6).

### 3.4 Playback service — host systemd unit (Python + ffmpeg)
- Exposes the **control API** over a Unix socket (or localhost-only TCP).
- Owns the DeckLink + GPU. Builds the concatenated playlist and runs `ffmpeg`
  with **NVDEC** decode and the **decklink** output muxer.
- Maintains a single playback state machine (§6.3) and reports it upstream.

### 3.5 Database — SQLite
- Single-file DB on a Docker volume. Sufficient for one server. Schema is written
  to be Postgres-portable (no SQLite-only features in app logic).

### 3.6 Printer — Epson thermal (ESC/POS)
- Driven by `python-escpos`. USB or network connection.
- Printer is **attached to the server**; the web UI triggers prints, the server
  performs them. (Browser-side printing is a possible future fallback.)

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
  duration_seconds (float), width, height, fps,
  video_codec, color_primaries, transfer_characteristics, is_hdr10 (bool),
  audio_summary, scanned_at

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
POST /playback/load     { showing_id, items: [{path, role, position}] }
POST /playback/start
POST /playback/pause
POST /playback/resume
POST /playback/stop      # "End Show"
GET  /playback/state     -> { state, showing_id, position_seconds, current_item }
```

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

- **Decode:** NVDEC (`-hwaccel cuda`) for efficient HEVC/AV1 HDR decode.
- **Output:** `-f decklink "<device name>"` muxer to the SDI card.
- **Playlist:** trailers then feature, played as an ordered sequence. Approach
  chosen during implementation: concat demuxer vs. sequential ffmpeg invocations
  managed by the service (sequential is simpler to pause/seek per-item; concat is
  smoother between items — to be validated on hardware).
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

### 9.1 Host prerequisites (documented, scripted later)
- NVIDIA driver + NVIDIA Container Toolkit.
- Blackmagic **Desktop Video** driver.
- NFS/SMB mount of remote media at `/mnt/media`.
- Epson printer reachable (USB device or network IP).

### 9.2 Docker Compose (management plane)
- `caddy` (:443), `frontend` (build artifact), `backend` (FastAPI),
  volume for SQLite, bind-mount `/mnt/media:ro`.
- Backend reaches the host playback service via the Unix socket / `host.docker.internal`.

### 9.3 Playback service (host)
- Installed as a **systemd** unit with access to `/dev/blackmagic*`, the GPU,
  and `/mnt/media`. Restart-on-failure.

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

- **Phase 0 — Design (this doc).**
- **Phase 1 — Management plane:** FastAPI + React + SQLite + Caddy in Compose;
  all four tabs functional against a **mock** playback service; ffprobe-based
  media scan; ticket ESC/POS rendering (print to file/mock).
- **Phase 2 — Wizard & scheduling:** New Showing wizard end-to-end; APScheduler
  triggers; runtime computation + rounding.
- **Phase 3 — Real playback service:** host systemd service, ffmpeg+NVDEC+DeckLink,
  shuttle controls wired to real hardware.
- **Phase 4 — HDR10 signaling + printer hardware + sync validation.**

Each phase is independently demoable; the mock playback service in Phase 1 lets
the entire UI be exercised before any hardware integration.
