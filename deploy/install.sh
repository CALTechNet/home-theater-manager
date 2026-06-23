#!/usr/bin/env bash
#
# Home Theater Manager — one-shot installer + CLI setup wizard.
#
# Usage (interactive CLI):
#   curl -fsSL https://raw.githubusercontent.com/CALTechNet/home-theater-manager/main/deploy/install.sh | sudo bash
#
# Supports: Ubuntu Server (22.04/24.04) and Rocky Linux (9/10).
# It installs Docker + Compose, clones the repo, walks you through CLI prompts to
# generate .env, then builds and starts the stack.
#
# Non-interactive: set env vars (see "Defaults" below) and add --non-interactive:
#   curl -fsSL .../install.sh | sudo HTM_MEDIA_HOST_PATH=/mnt/media bash -s -- --non-interactive
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults (overridable by env or the CLI)
# ---------------------------------------------------------------------------
REPO_URL="${HTM_REPO_URL:-https://github.com/CALTechNet/home-theater-manager.git}"
REPO_REF="${HTM_REPO_REF:-main}"
INSTALL_DIR="${HTM_INSTALL_DIR:-/opt/home-theater-manager}"

HTM_THEATER_NAME_WAS_SET=0
[ "${HTM_THEATER_NAME+x}" = "x" ] && HTM_THEATER_NAME_WAS_SET=1
HTM_THEATER_NAME="${HTM_THEATER_NAME:-Home Cinema}"
HTM_MEDIA_HOST_PATH="${HTM_MEDIA_HOST_PATH:-/mnt/media}"
HTM_SEAT_MAX_ROW="${HTM_SEAT_MAX_ROW:-F}"
HTM_SEAT_MAX_NUMBER="${HTM_SEAT_MAX_NUMBER:-6}"
HTM_TICKET_STYLE="${HTM_TICKET_STYLE:-receipt}"
HTM_DECKLINK_VERSION="${HTM_DECKLINK_VERSION:-16.0}"
export HTM_DECKLINK_VERSION

INTERACTIVE=1
for arg in "$@"; do
  case "$arg" in
    --non-interactive|--no-tui) INTERACTIVE=0 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
c_blue=$'\033[1;34m'; c_grn=$'\033[1;32m'; c_red=$'\033[1;31m'; c_yel=$'\033[1;33m'; c_off=$'\033[0m'
log()  { printf '%s==>%s %s\n' "$c_blue" "$c_off" "$*"; }
ok()   { printf '%s ok %s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s !! %s %s\n' "$c_yel" "$c_off" "$*"; }
die()  { printf '%s xx %s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

# A TTY for interactive prompts even when the script is piped from curl.
TTY="/dev/tty"
have_tty() { [ -e "$TTY" ] && [ -r "$TTY" ] && [ -w "$TTY" ]; }
require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "Please run as root (pipe to 'sudo bash')."
  fi
}

detect_os() {
  [ -r /etc/os-release ] || die "Cannot detect OS (/etc/os-release missing)."
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-}"
  OS_LIKE="${ID_LIKE:-}"
  case "$OS_ID" in
    ubuntu|debian) PKG="apt" ;;
    rocky|rhel|almalinux|centos|fedora) PKG="dnf" ;;
    *)
      case "$OS_LIKE" in
        *debian*) PKG="apt" ;;
        *rhel*|*fedora*) PKG="dnf" ;;
        *) die "Unsupported distro '$OS_ID'. Supported: Ubuntu, Rocky." ;;
      esac
      ;;
  esac
  ok "Detected $PRETTY_NAME (package manager: $PKG)"
}

# ---------------------------------------------------------------------------
# Dependency installation
# ---------------------------------------------------------------------------
install_base() {
  log "Installing base packages (git, curl, pciutils, usbutils)..."
  if [ "$PKG" = "apt" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl git pciutils usbutils
  else
    dnf install -y ca-certificates curl git pciutils usbutils
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker + Compose already present."
    return
  fi
  log "Installing Docker Engine + Compose plugin..."
  if [ "$PKG" = "apt" ]; then
    install -m 0755 -d /etc/apt/keyrings
    local repo="ubuntu"; [ "$OS_ID" = "debian" ] && repo="debian"
    curl -fsSL "https://download.docker.com/linux/${repo}/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    local codename; codename="$(. /etc/os-release; echo "${VERSION_CODENAME:-}")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${repo} ${codename} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    dnf install -y dnf-plugins-core || true
    if command -v dnf-3 >/dev/null 2>&1; then
      dnf-3 config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    elif dnf config-manager --help 2>&1 | grep -q -- '--add-repo'; then
      dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    else
      dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/centos/docker-ce.repo
    fi
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  systemctl enable --now docker
  ok "Docker installed."
}

# ---------------------------------------------------------------------------
# Repo
# ---------------------------------------------------------------------------
fetch_repo() {
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing checkout at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_REF"
    git -C "$INSTALL_DIR" checkout "$REPO_REF"
    git -C "$INSTALL_DIR" reset --hard "origin/$REPO_REF"
  else
    log "Cloning $REPO_URL ($REPO_REF) into $INSTALL_DIR..."
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
  fi
  ok "Repository ready at $INSTALL_DIR"
}

# Hardware auto-discovery (GPU/DeckLink/printer/audio) -> hardware.json + .env.
run_discovery() {
  log "Auto-discovering connected hardware..."
  mkdir -p "$INSTALL_DIR/runtime"
  bash "$INSTALL_DIR/deploy/discover.sh" "$INSTALL_DIR/runtime" || warn "Discovery had issues; continuing."
  # Pull primary GPU / DeckLink hints into this shell for .env.
  if [ -r "$INSTALL_DIR/runtime/hardware.env" ]; then
    # shellcheck disable=SC1091
    . "$INSTALL_DIR/runtime/hardware.env"
  fi
}

# Offer to install the Blackmagic DeckLink driver when a card is detected but no
# driver is loaded. Blackmagic has no public repo, so we ask for the package.
maybe_install_decklink() {
  [ "${HTM_HAS_DECKLINK:-false}" = "true" ] || return 0
  if lsmod 2>/dev/null | grep -qi blackmagic || ls /dev/blackmagic* >/dev/null 2>&1; then
    ok "DeckLink driver already loaded; skipping driver install."
    return 0
  fi
  if [ "$INTERACTIVE" -eq 0 ] || ! have_tty; then
    # Non-interactive: attempt install (script auto-tries the pinned CDN version
    # and skips cleanly if it needs a signed token / source).
    export HTM_DECKLINK_SRC="${HTM_DECKLINK_SRC:-}"
    bash "$INSTALL_DIR/deploy/install-decklink.sh" || warn "DeckLink install had issues."
    return 0
  fi

  echo
  echo "A DeckLink card was detected, but the Blackmagic driver is not loaded." > "$TTY"
  echo "The installer can try Desktop Video v${HTM_DECKLINK_VERSION:-16.0}, or you can paste a signed download link/local path." > "$TTY"
  cli_confirm "Install the SDI driver now?" "n" || return 0

  HTM_DECKLINK_SRC="$(cli_input "DeckLink package source (blank = auto-download)" "${HTM_DECKLINK_SRC:-}")"

  export HTM_DECKLINK_SRC
  bash "$INSTALL_DIR/deploy/install-decklink.sh" || warn "DeckLink install had issues; see output above."
}

# Install a global `htm` command pointing at the management menu.
install_htm_command() {
  ln -sf "$INSTALL_DIR/deploy/htm-menu.sh" /usr/local/bin/htm
  chmod +x "$INSTALL_DIR/deploy/htm-menu.sh" "$INSTALL_DIR/deploy/discover.sh" \
    "$INSTALL_DIR/deploy/install-decklink.sh" 2>/dev/null || true
  ok "Installed 'htm' management command (run: sudo htm)."
}

# ---------------------------------------------------------------------------
# CLI wizard. Falls back to env/defaults without a TTY.
# ---------------------------------------------------------------------------
cli_input() {
  local prompt="$1" default="${2:-}" answer
  if [ -n "$default" ]; then
    printf '%s [%s]: ' "$prompt" "$default" > "$TTY"
  else
    printf '%s: ' "$prompt" > "$TTY"
  fi
  IFS= read -r answer < "$TTY" || answer=""
  printf '%s' "${answer:-$default}"
}

cli_confirm() {
  local prompt="$1" default="${2:-y}" answer suffix
  if [ "$default" = "y" ]; then
    suffix="Y/n"
  else
    suffix="y/N"
  fi
  while true; do
    printf '%s [%s]: ' "$prompt" "$suffix" > "$TTY"
    IFS= read -r answer < "$TTY" || answer=""
    answer="${answer:-$default}"
    case "$answer" in
      y|Y|yes|YES|Yes) return 0 ;;
      n|N|no|NO|No) return 1 ;;
      *) echo "Please answer yes or no." > "$TTY" ;;
    esac
  done
}

cli_menu() {
  local prompt="$1" default="$2" choice
  while true; do
    echo "$prompt" > "$TTY"
    echo "  1) receipt  - Thermal receipt (80mm roll)" > "$TTY"
    echo "  2) fullpage - Full-page color ticket (8.5x11)" > "$TTY"
    choice="$(cli_input "Choose ticket style" "$default")"
    case "$choice" in
      1|receipt) printf '%s' "receipt"; return ;;
      2|fullpage) printf '%s' "fullpage"; return ;;
      *) echo "Please choose 1, 2, receipt, or fullpage." > "$TTY" ;;
    esac
  done
}

run_cli() {
  if [ "$INTERACTIVE" -eq 0 ] || ! have_tty; then
    warn "Running non-interactively; using defaults/env for configuration."
    return
  fi

  echo > "$TTY"
  echo "Home Theater Manager setup" > "$TTY"
  echo "This will configure the theater name, media location, seat grid, and ticket style." > "$TTY"

  local intro="This wizard configures your Home Theater Manager."
  if [ -r "$INSTALL_DIR/runtime/hardware.json" ]; then
    echo > "$TTY"
    echo "Detected hardware:" > "$TTY"
    echo "  GPU      : ${HTM_GPU_VENDOR:-Unknown} (decode: ${HTM_HWACCEL:-none})" > "$TTY"
    echo "  DeckLink : ${HTM_HAS_DECKLINK:-false}" > "$TTY"
    echo "Full details saved to runtime/hardware.json. You can re-run discovery any time with: sudo htm" > "$TTY"
  fi

  local theater_initial=""
  [ "$HTM_THEATER_NAME_WAS_SET" -eq 1 ] && theater_initial="$HTM_THEATER_NAME"
  echo > "$TTY"
  echo "$intro" > "$TTY"
  HTM_THEATER_NAME="$(cli_input "Theater name printed on tickets" "$theater_initial")"
  HTM_THEATER_NAME="${HTM_THEATER_NAME:-Home Cinema}"

  HTM_MEDIA_HOST_PATH="$(cli_input "Media location on this host" "$HTM_MEDIA_HOST_PATH")"

  HTM_SEAT_MAX_ROW="$(cli_input "Last seat row letter (A..Z)" "$HTM_SEAT_MAX_ROW")"

  HTM_SEAT_MAX_NUMBER="$(cli_input "Seats per row" "$HTM_SEAT_MAX_NUMBER")"

  # Tickets are generated as PDFs and printed from the operator's workstation to
  # any printer it can reach. Pick the default style (switchable per-print in UI).
  HTM_TICKET_STYLE="$(cli_menu "Default ticket style (changeable per print in the UI):" "$HTM_TICKET_STYLE")"

  echo > "$TTY"
  echo "Ready to deploy with:" > "$TTY"
  echo "  Theater : $HTM_THEATER_NAME" > "$TTY"
  echo "  Media   : $HTM_MEDIA_HOST_PATH" > "$TTY"
  echo "  Seats   : A-$HTM_SEAT_MAX_ROW x 1-$HTM_SEAT_MAX_NUMBER" > "$TTY"
  echo "  GPU     : ${HTM_GPU_VENDOR:-Unknown} / DeckLink ${HTM_HAS_DECKLINK:-false}" > "$TTY"
  echo "  Tickets : $HTM_TICKET_STYLE PDF (printed from your workstation)" > "$TTY"
  cli_confirm "Build and start now?" "y" || die "Aborted by user."
}

# ---------------------------------------------------------------------------
# Playback driver selection
# ---------------------------------------------------------------------------
# Pick the real ffmpeg/mpv runner when the host has a usable GPU render node or
# a DeckLink card; otherwise fall back to the mock simulator. Honor an explicit
# HTM_PLAYBACK_DRIVER from the environment. USE_GPU_COMPOSE adds the GPU DRM
# nodes (docker-compose.gpu.yml) so mpv --vo=drm can drive a GPU connector.
USE_GPU_COMPOSE=0
detect_playback() {
  local default="mock"
  if ls /dev/dri/renderD* >/dev/null 2>&1; then
    default="ffmpeg"
    USE_GPU_COMPOSE=1
  elif [ "${HTM_HAS_DECKLINK:-false}" = "true" ]; then
    default="ffmpeg"
  fi
  HTM_PLAYBACK_DRIVER="${HTM_PLAYBACK_DRIVER:-$default}"
  # No point attaching GPU nodes if the operator forced the mock driver.
  [ "$HTM_PLAYBACK_DRIVER" = "ffmpeg" ] || USE_GPU_COMPOSE=0
  export HTM_PLAYBACK_DRIVER
  log "Playback driver: $HTM_PLAYBACK_DRIVER (GPU DRM access: $([ "$USE_GPU_COMPOSE" -eq 1 ] && echo yes || echo no))"
}

# ---------------------------------------------------------------------------
# .env generation
# ---------------------------------------------------------------------------
write_env() {
  local env_file="$INSTALL_DIR/.env"
  local short_host fqdn first_ip https_addrs default_sni
  short_host="$(hostname 2>/dev/null || true)"
  fqdn="$(hostname -f 2>/dev/null || true)"
  first_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  default_sni="${first_ip:-${fqdn:-${short_host:-localhost}}}"
  https_addrs="https://localhost:443, https://127.0.0.1:443"
  [ -n "$first_ip" ] && https_addrs="${https_addrs}, https://${first_ip}:443"
  [ -n "$short_host" ] && https_addrs="${https_addrs}, https://${short_host}:443"
  [ -n "$fqdn" ] && [ "$fqdn" != "$short_host" ] && https_addrs="${https_addrs}, https://${fqdn}:443"

  # Host timezone so the backend scheduler fires showtimes at the right wall
  # clock (containers default to UTC). Honor an explicit HTM_TIMEZONE.
  local host_tz=""
  if command -v timedatectl >/dev/null 2>&1; then
    host_tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  fi
  [ -z "$host_tz" ] && [ -r /etc/timezone ] && host_tz="$(cat /etc/timezone 2>/dev/null || true)"
  if [ -z "$host_tz" ] && [ -L /etc/localtime ]; then
    host_tz="$(readlink -f /etc/localtime 2>/dev/null | sed 's#.*/zoneinfo/##')"
  fi
  host_tz="${HTM_TIMEZONE:-$host_tz}"
  [ -z "$host_tz" ] && host_tz="UTC"

  log "Writing $env_file"
  cat > "$env_file" <<EOF
# Generated by deploy/install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
HTM_HTTPS_SITE_ADDRS=${https_addrs}
HTM_TLS_DEFAULT_SNI=${default_sni}
HTM_DATABASE_URL=sqlite:////data/htm.db
HTM_MEDIA_HOST_PATH=${HTM_MEDIA_HOST_PATH}
HTM_MEDIA_ROOT=/mnt/media
HTM_PLAYBACK_URL=http://playback:9000
# mock = in-memory simulator (no real output); ffmpeg = real ffmpeg/mpv runner.
HTM_PLAYBACK_DRIVER=${HTM_PLAYBACK_DRIVER:-mock}
HTM_THEATER_NAME=${HTM_THEATER_NAME}
HTM_SEAT_MAX_ROW=${HTM_SEAT_MAX_ROW}
HTM_SEAT_MAX_NUMBER=${HTM_SEAT_MAX_NUMBER}
HTM_TICKET_STYLE=${HTM_TICKET_STYLE:-receipt}
# Timezone the operator schedules in; the scheduler localizes showtimes to it so
# scheduled showings auto-start at the right wall-clock time. TZ also sets the
# container clock/log timestamps.
HTM_TIMEZONE=${host_tz}
TZ=${host_tz}
HTM_HARDWARE_FILE=/runtime/hardware.json
# Hardware hints from auto-discovery (informational; consumed by Phase 3 playback)
HTM_GPU_VENDOR=${HTM_GPU_VENDOR:-Unknown}
HTM_HWACCEL=${HTM_HWACCEL:-none}
HTM_HAS_DECKLINK=${HTM_HAS_DECKLINK:-false}
EOF
  if [ "${USE_GPU_COMPOSE:-0}" -eq 1 ]; then
    # COMPOSE_FILE makes every `docker compose` command (deploy, htm menu, manual)
    # include the GPU override that maps /dev/dri into the playback container.
    {
      echo "# GPU/KMS playback: attach DRM nodes for mpv --vo=drm."
      echo "COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml"
    } >> "$env_file"
  fi
  # Ensure the media path exists so the read-only mount doesn't fail.
  mkdir -p "$HTM_MEDIA_HOST_PATH" 2>/dev/null || warn "Could not create $HTM_MEDIA_HOST_PATH (mount it before first scan)."
  ok ".env written."
}

# ---------------------------------------------------------------------------
# Build + start
# ---------------------------------------------------------------------------
deploy() {
  log "Building and starting containers (this may take a few minutes)..."
  local -a files=(-f docker-compose.yml)
  [ "${USE_GPU_COMPOSE:-0}" -eq 1 ] && files+=(-f docker-compose.gpu.yml)
  ( cd "$INSTALL_DIR" && docker compose "${files[@]}" up -d --build )
  ok "Stack is up."
}

print_done() {
  local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  cat <<EOF

${c_grn}Home Theater Manager is running.${c_off}

  Open:   https://${ip:-<server-ip>}/
          (self-signed TLS — your browser will warn once; accept it)

  Manage: cd $INSTALL_DIR
          docker compose ps        # status
          docker compose logs -f   # logs
          docker compose down      # stop

  Config: $INSTALL_DIR/.env   (re-run installer or edit, then 'docker compose up -d')

  Manage: sudo htm   (CLI: re-discover hardware, console/video routing, logs, update)

Console: this is a server OS. If a GPU connector drives the projector, route the
VGA text console to a different output (and optionally add a serial console):
  sudo bash $INSTALL_DIR/deploy/console-routing.sh --list
DeckLink SDI playback needs nothing here — SDI leaves the VGA console free.

Printing: tickets print from the workstation/browser — pick any printer it can
reach (network, USB, thermal, or a normal 8.5x11 color printer) in the print
dialog. The server only outputs to the projector + audio.

Next: open the Media tab and click "Scan library" to index your files.

Playback driver: ${HTM_PLAYBACK_DRIVER}.
EOF
  if [ "${HTM_PLAYBACK_DRIVER}" = "ffmpeg" ] && [ "${USE_GPU_COMPOSE:-0}" -eq 1 ]; then
    cat <<EOF
GPU output is enabled (mpv --vo=drm drives a GPU connector). For video to reach
the projector, free that connector from the Linux text console, then reboot:
  sudo bash $INSTALL_DIR/deploy/console-routing.sh --list
  sudo bash $INSTALL_DIR/deploy/console-routing.sh --video-output <CONNECTOR> --apply
Then select that output in Settings. The idle screen (black or logo) shows
whenever no show is playing; the show plays when you start it.
EOF
  elif [ "${HTM_PLAYBACK_DRIVER}" = "mock" ]; then
    cat <<EOF
NOTE: running the MOCK playback engine — it simulates state but produces no real
video. Set HTM_PLAYBACK_DRIVER=ffmpeg in $INSTALL_DIR/.env (GPU or DeckLink
required) and re-run to enable real output.
EOF
  fi
}

main() {
  require_root
  detect_os
  install_base
  install_docker
  fetch_repo
  run_discovery
  install_htm_command
  run_cli
  maybe_install_decklink
  detect_playback
  write_env
  deploy
  print_done
}

main "$@"
